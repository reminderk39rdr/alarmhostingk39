# -*- coding: utf-8 -*-
# telegram_bot.py — RDR Hosting Reminder Telegram Integration — FINAL & ABADI

import os
import httpx
import logging
from datetime import datetime, date
from zoneinfo import ZoneInfo
from collections import defaultdict
from html import escape as html_escape
from typing import Optional, Any, Iterable

from database import SessionLocal
from crud import get_all_subscriptions, add_log

logger = logging.getLogger(__name__)
timezone_wib = ZoneInfo("Asia/Jakarta")

TELEGRAM_MAX_LEN = 3500  # aman di bawah limit 4096


async def send_telegram_message(text: str) -> bool:
    """Kirim pesan ke telegram. Return True kalau sukses."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        logger.error("[TELEGRAM] Token atau Chat ID kosong!")
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

        data = r.json()
        if data.get("ok"):
            logger.info("[TELEGRAM] Pesan terkirim!")
            return True

        logger.error(f"[TELEGRAM] Gagal kirim: {r.text}")
        return False

    except Exception as e:
        logger.error(f"[TELEGRAM] Error: {e}")
        return False


def _to_date(value: Any) -> Optional[date]:
    """Pastikan expires_at jadi date."""
    if value is None:
        return None
    try:
        return value.date() if hasattr(value, "date") else value
    except Exception:
        return None


def _chunks(text: str, size: int = TELEGRAM_MAX_LEN) -> Iterable[str]:
    """Split text jadi beberapa chunk biar gak kena limit Telegram."""
    for i in range(0, len(text), size):
        yield text[i : i + size]


def _allowed_minute(windows: set[int]) -> bool:
    """
    Anti-burst: cuma boleh kirim kalau sekarang ada di minute window yang diizinkan.
    Berguna kalau server restart dan APScheduler nge-run job yang "missed".
    """
    now_minute = datetime.now(timezone_wib).minute
    return now_minute in windows


def _format_remaining(days_left: int) -> tuple[str, str]:
    """
    Return (remaining_text, emoji_override_optional)
    - expired: (<b>Sudah Expired X Hari</b>)
    - hari ini: (<b>Jatuh Tempo Hari Ini</b>)
    - besok: (<b>Besok Jatuh Tempo</b>)
    - lainnya: (X hari lagi)
    """
    if days_left < 0:
        expired_days = abs(days_left)
        return f"(<b>Sudah Expired {expired_days} Hari</b>)", "💀"
    if days_left == 0:
        return "(<b>Jatuh Tempo Hari Ini</b>)", "💀"
    if days_left == 1:
        return "(<b>Besok Jatuh Tempo</b>)", "⏳"
    return f"({days_left} hari lagi)", ""


def _default_emoji(days_left: int) -> str:
    """Emoji default kalau tidak dioverride oleh _format_remaining."""
    if days_left <= 1:
        return "💀"
    if days_left == 2:
        return "⚠️"
    if days_left == 3:
        return "🔥"
    if days_left <= 7:
        return "⚠️"
    return "✅"


# =========================================================
# 1) FULL LIST / DAILY SUMMARY
# =========================================================
async def send_full_list_trigger():
    """Generate & kirim list hosting lengkap ke Telegram."""
    db = SessionLocal()
    try:
        subs = get_all_subscriptions(db)

        now_dt = datetime.now(timezone_wib)
        today_date = now_dt.date()
        now_str = now_dt.strftime("%d %B %Y - %H:%M WIB")

        if not subs:
            msg = "<b>Our Hosting List</b>\n\nBelum ada subscription bro! 🚀"
            await send_telegram_message(msg)
            add_log(db, "Send full list: kosong", "INFO")
            return

        grouped = defaultdict(list)
        for sub in subs:
            brand = (sub.brand or "Tanpa Brand").strip().upper()
            grouped[brand].append(sub)

        message = f"<b>Our Hosting List</b>\n{now_str}\n\n"

        for brand, items in sorted(grouped.items()):
            message += f"<b>{html_escape(brand)}</b>\n"

            for i, sub in enumerate(items, 1):
                expires_date = _to_date(sub.expires_at)
                if expires_date is None:
                    days_left = 999999
                else:
                    days_left = (expires_date - today_date).days

                safe_name = html_escape(sub.name or "Tanpa Nama")
                message += f"{i}. <b>{safe_name}</b>\n"

                if getattr(sub, "url", None):
                    safe_url = html_escape(sub.url)
                    message += f"🔗 <a href='{safe_url}'>{safe_url}</a>\n"

                if expires_date:
                    remaining_text, emoji_override = _format_remaining(days_left)
                    emoji = emoji_override or _default_emoji(days_left)

                    message += (
                        f"Expire: {expires_date.strftime('%d %B %Y')} "
                        f"{remaining_text} {emoji}\n\n"
                    )
                else:
                    message += "Expire: - (unknown) ✅\n\n"

            message += "—" * 30 + "\n\n"

        total = len(subs)
        message += f"<b>TOTAL: {total} SUBSCRIPTION{'S' if total != 1 else ''}</b>"

        for ch in _chunks(message):
            await send_telegram_message(ch)

        add_log(db, f"Send full list: {total} item", "INFO")

    except Exception as e:
        logger.error(f"Error di send_full_list_trigger: {e}")
        await send_telegram_message("Error bro! Gagal generate list.")
        add_log(db, f"Send full list error: {e}", "ERROR")
    finally:
        db.close()


async def send_daily_summary():
    """Daily summary = full list jam 09:00."""
    if not _allowed_minute({0}):
        return
    await send_full_list_trigger()


# =========================================================
# 2) REMINDER BERTINGKAT
# =========================================================
async def _send_filtered_reminders(target_days: list[int], title: str):
    """Kirim reminder hanya untuk subscription yang days_left ada di target_days."""
    db = SessionLocal()
    try:
        subs = get_all_subscriptions(db)
        now_dt = datetime.now(timezone_wib)
        today_date = now_dt.date()
        now_str = now_dt.strftime("%d %B %Y - %H:%M WIB")

        matched = []
        for sub in subs:
            expires_date = _to_date(sub.expires_at)
            if expires_date is None:
                continue
            days_left = (expires_date - today_date).days
            if days_left in target_days:
                matched.append((sub, expires_date, days_left))

        if not matched:
            return

        grouped = defaultdict(list)
        for sub, expires_date, days_left in matched:
            brand = (sub.brand or "Tanpa Brand").strip().upper()
            grouped[brand].append((sub, expires_date, days_left))

        msg = f"<b>{html_escape(title)}</b>\n{now_str}\n\n"

        for brand, items in sorted(grouped.items()):
            msg += f"<b>{html_escape(brand)}</b>\n"

            for i, (sub, expires_date, days_left) in enumerate(items, 1):
                safe_name = html_escape(sub.name or "Tanpa Nama")
                msg += f"{i}. <b>{safe_name}</b>\n"

                if sub.url:
                    safe_url = html_escape(sub.url)
                    msg += f"🔗 <a href='{safe_url}'>{safe_url}</a>\n"

                remaining_text, emoji_override = _format_remaining(days_left)
                emoji = emoji_override or _default_emoji(days_left)

                msg += (
                    f"Expire: {expires_date.strftime('%d %B %Y')} "
                    f"{remaining_text} {emoji}\n\n"
                )

            msg += "—" * 30 + "\n\n"

        await send_telegram_message(msg)
        add_log(db, f"Reminder sent: {title} ({len(matched)} item)", "WARN")

    finally:
        db.close()


async def send_reminders_3days():
    """H-3 → 3x sehari (minute 0)."""
    if not _allowed_minute({0}):
        return
    await _send_filtered_reminders([3], "⚠️ Reminder 3 Hari Lagi")


async def send_reminders_2days():
    """H-2 → 6x sehari (minute 0)."""
    if not _allowed_minute({0}):
        return
    await _send_filtered_reminders([2], "🚨 Reminder 2 Hari Lagi")


async def send_reminders_1day_or_expired():
    """H-1 / H / expired → bising tiap 30 menit (minute 0 & 30)."""
    if not _allowed_minute({0, 30}):
        return

    db = SessionLocal()
    try:
        subs = get_all_subscriptions(db)
        now_dt = datetime.now(timezone_wib)
        today_date = now_dt.date()

        targets = set()
        for sub in subs:
            expires_date = _to_date(sub.expires_at)
            if expires_date is None:
                continue
            days_left = (expires_date - today_date).days
            if days_left <= 1:  # H-1, H, expired
                targets.add(days_left)

        if targets:
            await _send_filtered_reminders(
                sorted(targets),
                "💀 URGENT! 1 Hari / Expired",
            )

    finally:
        db.close()
