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


async def send_telegram_message(text: str):
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
        "disable_web_page_preview": True
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(url, json=payload)
            if r.json().get("ok"):
                logger.info("[TELEGRAM] Pesan terkirim!")
                return True
            else:
                logger.error(f"[TELEGRAM] Gagal kirim: {r.text}")
    except Exception as e:
        logger.error(f"[TELEGRAM] Error: {e}")
    return False


async def send_full_list_trigger():
    db = SessionLocal()
    try:
        subs = get_all_subscriptions(db)
        today = datetime.now(timezone_wib)
        now_str = today.strftime('%d %B %Y - %H:%M WIB')

        if not subs:
            await send_telegram_message("Our Hosting List\n\nBelum ada subscription bro! Rocket")
            return

        # Grouping berdasarkan brand
        grouped = defaultdict(list)
        for sub in subs:
            brand = (sub.brand or "Tanpa Brand").strip().upper()
            grouped[brand].append(sub)

        message = f"<b>Our Hosting List</b>\n{now_str}\n\n"

        for brand, items in sorted(grouped.items()):
            message += f"<b>{brand}</b>\n"
            for i, sub in enumerate(items, 1):
                days_left = (sub.expires_at - today.date()).days

                # EMOJI ASLI — 100% KELUAR DI TELEGRAM
              if days_left < 0:
                    emoji = "💀"
                elif days_left == 0:
                    emoji = "💀"
                elif days_left <= 3:
                    emoji = "🔥"
                elif days_left <= 7:
                    emoji = "⚠️"
                else:
                    emoji = "✅"

                message += f"{i}. <b>{sub.name}</b>\n"
                message += f"   <a href='{sub.url}'>{sub.url}</a>\n"
                message += f"   Expire: {sub.expires_at.strftime('%d %B %Y')} ({days_left} hari lagi) {emoji}\n\n"

            message += "—" * 30 + "\n\n"

        total = len(subs)
        message += f"<b>TOTAL: {total} SUBSCRIPTION{'S' if total != 1 else ''}</b>"

        await send_telegram_message(message)

    except Exception as e:
        logger.error(f"Error di send_full_list_trigger: {e}")
        await send_telegram_message("Error bro! Gagal generate list.")
    finally:
        db.close()


async def send_daily_summary():
    pass
