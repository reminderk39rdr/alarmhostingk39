# telegram_bot.py
import os
import httpx
from datetime import datetime
from zoneinfo import ZoneInfo

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

timezone_wib = ZoneInfo("Asia/Jakarta")

async def send_telegram_message(text: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("TELEGRAM_BOT_TOKEN atau TELEGRAM_CHAT_ID belum di-set.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=payload)
            if response.status_code != 200:
                print(f"Gagal kirim Telegram: {response.text}")
            else:
                print(f"Pesan terkirim: {text[:50]}...")
    except Exception as e:
        print(f"Error saat kirim Telegram: {e}")

async def send_daily_summary(subscriptions):
    if not subscriptions:
        await send_telegram_message("📋 Daftar Hosting\n\nTidak ada subscription terdaftar.")
        return

    brand_dict = {}
    for sub in subscriptions:
        brand = sub.brand or "Tidak Dikategorikan"
        if brand not in brand_dict:
            brand_dict[brand] = []
        brand_dict[brand].append(sub)

    today_wib = datetime.now(timezone_wib).date()
    message_lines = [f"📋 Daily Summary ({today_wib.strftime('%d %B %Y')})\n"]

    for brand in sorted(brand_dict.keys()):
        subs = brand_dict[brand]
        message_lines.append(f"\n<b>{brand.upper()}</b>")
        for sub in subs:
            days_left = (sub.expires_at - today_wib).days
            if days_left < 0:
                status = f"🔴 Kadaluarsa {-days_left} hari yang lalu"
            elif days_left == 0:
                status = "🔴 Berakhir hari ini"
            elif days_left == 1:
                status = "🔴 Besok berakhir – mohon segera perpanjang"
            elif days_left <= 3:
                status = f"⚠️ Tersisa {days_left} hari lagi"
            else:
                status = f"Tersisa {days_left} hari"

            message_lines.append(
                f"  • <a href='{sub.url}'>{sub.name}</a>\n"
                f"    Expire: {sub.expires_at.strftime('%d %b %Y')} | {status}"
            )

    full_message = "\n".join(message_lines)
    await send_telegram_message(full_message)