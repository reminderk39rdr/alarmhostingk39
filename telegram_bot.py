# telegram_bot.py — VERSI FINAL YANG GA PERNAH ERROR LAGI
import os
import httpx
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
timezone_wib = ZoneInfo("Asia/Jakarta")

async def send_telegram_message(text: str):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    if not token or not chat_id:
        logger.error("[TELEGRAM] Token atau Chat ID kosong bro!")
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
            if r.status_code == 200 and r.json().get("ok"):
                logger.info("[TELEGRAM] Sukses terkirim!")
                return True
            else:
                logger.error(f"[TELEGRAM] Gagal: {r.text}")
    except Exception as e:
        logger.error(f"[TELEGRAM] Error: {e}")
    return False

# FUNGSI INI YANG SELALU LUPA DITAMBAHIN — INI PENYEBAB ERROR IMPORT!
async def send_daily_summary(subs):
    if not subs:
        return

    today = datetime.now(timezone_wib).strftime("%d %B %Y")
    message = f"📊 <b>K39 Daily Report - {today}</b>\n\n"

    critical = [s for s in subs if (s.expires_at - datetime.now(timezone_wib).date()).days <= 7]
    
    if critical:
        message += "<b>⚠️ EXPIRING SOON (7 hari ke bawah):</b>\n\n"
        for s in critical:
            days = (s.expires_at - datetime.now(timezone_wib).date()).days
            emoji = "💀" if days <= 0 else "🔴" if days <= 2 else "🟠"
            message += f"{emoji} <b>{s.name}</b> → {days} hari lagi\nExpire: {s.expires_at.strftime('%d %B %Y')}\n{s.url}\n\n"
    else:
        message += "✅ Semua aman bro! Ga ada yang expire minggu ini 🔥\n\n"

    message += f"Total subscription: {len(subs)} items | {datetime.now(timezone_wib).strftime('%H:%M WIB')}"
    
    await send_telegram_message(message)
