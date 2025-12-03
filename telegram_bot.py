# telegram_bot.py — RDR Hosting Reminder Telegram Integration — FINAL & ABADI

import os
import httpx
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from collections import defaultdict

from database import SessionLocal
from crud import get_all_subscriptions

logger = logging.getLogger(__name__)
timezone_wib = ZoneInfo("Asia/Jakarta")


async def send_telegram_message(text: str) -> bool:
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
        else:
            logger.error(f"[TELEGRAM] Gagal kirim: {r.text}")
            return False

    except Exception as e:
        logger.error(f"[TELEGRAM] Error: {e}")
        return False


async def send_full_list_trigger():
    db = SessionLocal()
    try:
        subs = get_all_subscriptions(db)
        today_dt = datetime.now(timezone_wib)
        today_date = today_dt.date()
        now_str = today_dt.strftime("%d %B %Y - %H:%M WIB")

        if not subs:
            await send_telegram_message(
                "Our Hosting List\n\nBelum ada subscription bro! 🚀"
            )
            return

        # Grouping berdasarkan brand
        grouped = defaultdict(list)
        for sub in subs:
            brand = (sub.brand or "Tanpa Brand").strip().upper()
            grouped[brand].append(sub)

        message = f"Our Hosting List\n{now_str}\n\n"

        for brand, items in sorted(grouped.items()):
            message += f"<b>{brand}</b>\n"
            for i, sub in enumerate(items, 1):
                # pastikan expires_at itu date/datetime
                expires_date = (
                    sub.expires_at.date()
                    if hasattr(sub.expires_at, "date")
                    else sub.expires_at
                )

                days_left = (expires_date - today_date).days

                # EMOJI ASLI — 100% KELUAR DI TELEGRAM
                if days_left < 0:
                    emoji = "🛠️"  # lewat
                elif days_left == 0:
                    emoji = "🛠️"  # hari ini
                elif days_left <= 3:
                    emoji = "🔥"
                elif days_left <= 7:
                    emoji = "⚠️"
                else:
                    emoji = "✅"

                message += f"{i}. <b>{sub.name}</b>\n"
                if sub.url:
                    message += f"🔗 {sub.url}\n"
                message += (
                    f"Expire: {expires_date.strftime('%d %B %Y')} "
                    f"({days_left} hari lagi) {emoji}\n\n"
                )

            message += "—" * 30 + "\n\n"

        total = len(subs)
        message += f"TOTAL: {total} SUBSCRIPTION{'S' if total != 1 else ''}"

        await send_telegram_message(message)

    except Exception as e:
        logger.error(f"Error di send_full_list_trigger: {e}")
        await send_telegram_message("Error bro! Gagal generate list.")

    finally:
        db.close()


async def send_daily_summary():
    """
    Placeholder fungsi biar import di main.py nggak error.
    Isi sesuai kebutuhan kalau mau daily summary.
    """
    await send_full_list_trigger()
