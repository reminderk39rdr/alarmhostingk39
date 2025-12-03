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
from crud import get_all_subscriptions

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
    # datetime punya .date(), date juga punya .date tapi return dirinya sendiri
    try:
        return value.date() if hasattr(value, "date") else value
    except Exception:
        return None


def _chunks(text: str, size: int = TELEGRAM_MAX_LEN) -> Iterable[str]:
    """Split text jadi beberapa chunk biar gak kena limit Telegram."""
    for i in range(0, len(text), size):
        yield text[i : i + size]


async def send_full_list_trigger():
    """Generate & kirim list hosting lengkap ke Telegram."""
    db = SessionLocal()
    try:
        subs = get_all_subscriptions(db)

        now_dt = datetime.now(timezone_wib)
        today_date = now_dt.date()
        now_str = now_dt.strftime("%d %B %Y - %H:%M WIB")

        if not subs:
            await send_telegram_message(
                "<b>Our Hosting List</b>\n\nBelum ada subscription bro! 🚀"
            )
            return

        # Grouping berdasarkan brand
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

                # EMOJI UNICODE ASLI — PASTI KELUAR DI TELEGRAM
                if days_left < 0:
                    emoji = "💀"   # sudah kadaluarsa
                elif days_left == 0:
                    emoji = "💀"   # jatuh tempo hari ini
                elif days_left <= 3:
                    emoji = "🔥"   # sangat mendesak
                elif days_left <= 7:
                    emoji = "⚠️"   # peringatan
                else:
                    emoji = "✅"   # aman

                safe_name = html_escape(sub.name or "Tanpa Nama")

                message += f"{i}. <b>{safe_name}</b>\n"

                if getattr(sub, "url", None):
                    safe_url = html_escape(sub.url)
                    message += f"🔗 <a href='{safe_url}'>{safe_url}</a>\n"

                if expires_date:
                    message += (
                        f"Expire: {expires_date.strftime('%d %B %Y')} "
                        f"({days_left} hari lagi) {emoji}\n\n"
                    )
                else:
                    message += f"Expire: - (unknown) {emoji}\n\n"

            message += "—" * 30 + "\n\n"

        total = len(subs)
        message += f"<b>TOTAL: {total} SUBSCRIPTION{'S' if total != 1 else ''}</b>"

        # kirim per chunk biar gak kepanjangan
        for ch in _chunks(message):
            await send_telegram_message(ch)

    except Exception as e:
        logger.error(f"Error di send_full_list_trigger: {e}")
        await send_telegram_message("Error bro! Gagal generate list.")
    finally:
        db.close()


async def send_daily_summary():
    """
    Daily summary sementara = full list.
    Bisa kamu ganti logicnya kapan aja.
    """
    await send_full_list_trigger()
