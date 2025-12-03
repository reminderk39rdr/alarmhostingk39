import os
import httpx
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from collections import defaultdict
from typing import Iterable
import html

from database import SessionLocal
from crud import get_all_subscriptions, set_last_notified, add_log

logger = logging.getLogger(__name__)
timezone_wib = ZoneInfo("Asia/Jakarta")

TELEGRAM_MAX_LEN = 3500


def html_escape(s: str) -> str:
    return html.escape(s or "")


def _to_date(value):
    return value.date() if hasattr(value, "date") else value


def _chunks(text: str, size: int = TELEGRAM_MAX_LEN) -> Iterable[str]:
    for i in range(0, len(text), size):
        yield text[i:i + size]


def _allowed_minute(windows: set[int]) -> bool:
    return datetime.now(timezone_wib).minute in windows


def _format_remaining(days_left: int) -> tuple[str, str]:
    if days_left < 0:
        expired_days = abs(days_left)
        return f"(<b>Sudah Expired {expired_days} Hari</b>)", "💀"
    if days_left == 0:
        return "(<b>Jatuh Tempo Hari Ini</b>)", "💀"
    if days_left == 1:
        return "(<b>Besok Jatuh Tempo</b>)", "⏳"
    return f"({days_left} hari lagi)", ""


def _default_emoji(days_left: int) -> str:
    if days_left <= 1:
        return "💀"
    if days_left == 2:
        return "⚠️"
    if days_left == 3:
        return "🔥"
    if days_left <= 7:
        return "⚠️"
    return "✅"


async def send_telegram_message(text: str) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        logger.error("[TELEGRAM] Token/Chat ID kosong.")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(url, json=payload)
        return bool(r.json().get("ok"))
    except Exception as e:
        logger.error(f"[TELEGRAM] Error: {e}")
        return False


# =========================================================
# FULL LIST / DAILY
# =========================================================
async def send_full_list_trigger(stage: str = "DAILY"):
    db = SessionLocal()
    try:
        subs = get_all_subscriptions(db)
        now_dt = datetime.now(timezone_wib)
        today = now_dt.date()
        now_str = now_dt.strftime("%d %B %Y - %H:%M WIB")

        if not subs:
            await send_telegram_message("<b>Our Hosting List</b>\n\nBelum ada subscription bro! 🚀")
            return

        grouped = defaultdict(list)
        for sub in subs:
            brand = (sub.brand or "Tanpa Brand").strip().upper()
            grouped[brand].append(sub)

        msg = f"<b>Our Hosting List</b>\n{now_str}\n\n"

        for brand, items in sorted(grouped.items()):
            msg += f"<b>{html_escape(brand)}</b>\n"
            for i, sub in enumerate(items, 1):
                exp_date = _to_date(sub.expires_at)
                days_left = (exp_date - today).days

                msg += f"{i}. <b>{html_escape(sub.name)}</b>\n"
                if sub.url:
                    safe_url = html_escape(sub.url)
                    msg += f"🔗 <a href='{safe_url}'>{safe_url}</a>\n"

                remaining_text, emoji_override = _format_remaining(days_left)
                emoji = emoji_override or _default_emoji(days_left)
                msg += f"Expire: {exp_date.strftime('%d %B %Y')} {remaining_text} {emoji}\n\n"

        msg += f"<b>TOTAL: {len(subs)} SUBSCRIPTION{'S' if len(subs)!=1 else ''}</b>"

        ok_any = False
        for ch in _chunks(msg):
            ok_any = ok_any or await send_telegram_message(ch)

        add_log(db, "INFO", f"Telegram full list sent ({stage}). ok={ok_any}")

    except Exception as e:
        add_log(db, "ERROR", f"Telegram full list error: {e}")
    finally:
        db.close()


async def send_daily_summary():
    if not _allowed_minute({0}):
        return
    await send_full_list_trigger(stage="DAILY")


# =========================================================
# REMINDER WINDOWS
# =========================================================
async def _send_filtered(target_days: list[int], title: str, stage: str):
    db = SessionLocal()
    try:
        subs = get_all_subscriptions(db)
        now_dt = datetime.now(timezone_wib)
        today = now_dt.date()
        now_str = now_dt.strftime("%d %B %Y - %H:%M WIB")

        matched = []
        for sub in subs:
            exp_date = _to_date(sub.expires_at)
            days_left = (exp_date - today).days
            if days_left in target_days:
                matched.append((sub, exp_date, days_left))

        if not matched:
            return

        grouped = defaultdict(list)
        for sub, exp_date, days_left in matched:
            brand = (sub.brand or "Tanpa Brand").strip().upper()
            grouped[brand].append((sub, exp_date, days_left))

        msg = f"<b>{html_escape(title)}</b>\n{now_str}\n\n"

        for brand, items in sorted(grouped.items()):
            msg += f"<b>{html_escape(brand)}</b>\n"
            for i, (sub, exp_date, days_left) in enumerate(items, 1):
                msg += f"{i}. <b>{html_escape(sub.name)}</b>\n"
                if sub.url:
                    safe_url = html_escape(sub.url)
                    msg += f"🔗 <a href='{safe_url}'>{safe_url}</a>\n"

                remaining_text, emoji_override = _format_remaining(days_left)
                emoji = emoji_override or _default_emoji(days_left)
                msg += f"Expire: {exp_date.strftime('%d %B %Y')} {remaining_text} {emoji}\n\n"

                set_last_notified(db, sub.id, stage)

            msg += "—" * 30 + "\n\n"

        ok = await send_telegram_message(msg)
        add_log(db, "INFO", f"Reminder sent stage={stage} ok={ok} count={len(matched)}")

    except Exception as e:
        add_log(db, "ERROR", f"Reminder error stage={stage}: {e}")
    finally:
        db.close()


async def send_reminders_3days():
    if not _allowed_minute({0}):
        return
    await _send_filtered([3], "Reminder H-3 (3x sehari)", "H-3")


async def send_reminders_2days():
    if not _allowed_minute({0}):
        return
    await _send_filtered([2], "Reminder H-2 (6x sehari)", "H-2")


async def send_reminders_1day_or_expired():
    if not _allowed_minute({0, 30}):
        return
    await _send_filtered(
        [1, 0, -1, -2, -3, -4, -5, -6, -7, -8, -9, -10],
        "Reminder H-1 / Jatuh Tempo / Expired",
        "H-1/EXPIRED",
    )
