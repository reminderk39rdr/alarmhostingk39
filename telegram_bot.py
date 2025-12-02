import os
import httpx
from datetime import datetime
from zoneinfo import ZoneInfo

timezone_wib = ZoneInfo("Asia/Jakarta")

async def send_telegram_message(text: str):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(url, data=payload)
    except Exception as e:
        print(f"Telegram error: {e}")

async def send_daily_summary(subs):
    today = datetime.now(timezone_wib).strftime("%d %B %Y")
    message = f"📊 <b>K39 Daily Report - {today}</b>\n\n"

    critical = [s for s in subs if (s.expires_at - datetime.now(timezone_wib).date()).days <= 7]
    if critical:
        message += "<b>⚠️ PERINGATAN EXPIRE DALAM 7 HARI:</b>\n\n"
        for s in critical:
            days = (s.expires_at - datetime.now(timezone_wib).date()).days
            emoji = "💀" if days <= 0 else "🔴" if days <= 2 else "🟠"
            message += f"{emoji} <b>{s.name}</b> → {days} hari lagi\nExpire: {s.expires_at.strftime('%d %B %Y')}\n{s.url}\n\n"
    else:
        message += "✅ Semua subscription aman bro!\n"

    message += f"\nTotal aktif: {len(subs)} items | {datetime.now(timezone_wib).strftime('%H:%M %Z')}"
    await send_telegram_message(message)