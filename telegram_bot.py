# telegram_bot.py

import os
import httpx
from datetime import datetime
from zoneinfo import ZoneInfo

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
timezone_wib = ZoneInfo("Asia/Jakarta")

async def send_telegram_message(text: str):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }

    async with httpx.AsyncClient() as client:
        try:
            await client.post(url, json=payload, timeout=10)
        except:
            pass

async def send_daily_summary(subscriptions):
    if not subscriptions:
        await send_telegram_message("📋 *Daily Summary* — Tidak ada subscription aktif")
        return

    today = datetime.now(timezone_wib).date()
    lines = [f"📋 *Daily Summary Hosting* — {today.strftime('%d %B %Y')}\n"]

    brand_dict = {}
    for sub in subscriptions:
        brand = sub.brand or "Lainnya"
        brand_dict.setdefault(brand, []).append(sub)

    for brand, subs in sorted(brand_dict.items()):
        lines.append(f"\n*{brand.upper()}*")
        for sub in subs:
            days = (sub.expires_at - today).days
            if days < 0:
                status = f"🔴 Kadaluarsa {-days} hari lalu"
            elif days == 0:
                status = "🔴 Expire hari ini"
            elif days == 1:
                status = "🔴 Besok expire — segera renew!"
            elif days <= 3:
                status = f"⚠️ Tinggal {days} hari lagi"
            else:
                status = f"{days} hari lagi"

            lines.append(f"• {sub.name}\n  Expire: {sub.expires_at.strftime('%d %b %Y')} | {status}\n  {sub.url}")

    await send_telegram_message("\n".join(lines))