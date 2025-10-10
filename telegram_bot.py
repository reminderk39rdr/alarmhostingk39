# telegram_bot.py
import os
import httpx
from datetime import date, datetime
from zoneinfo import ZoneInfo # Import tambahan

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Zona waktu WIB
timezone_wib = ZoneInfo("Asia/Jakarta")

async def send_telegram_message(text: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ TELEGRAM_BOT_TOKEN atau TELEGRAM_CHAT_ID belum di-set.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=payload)
            if response.status_code != 200:
                print(f"❌ Gagal kirim Telegram: {response.text}")
            else:
                print(f"✅ Pesan terkirim ke Telegram: {text[:50]}...")
    except Exception as e:
        print(f"🚨 Error saat kirim Telegram: {e}")

# Fungsi untuk mengirim daily summary - BERDASARKAN BRAND
async def send_daily_summary(subscriptions):
    """
    Kirim daftar lengkap subscription ke Telegram, dikelompokkan berdasarkan brand.
    subscriptions: list objek Subscription SQLAlchemy
    """
    if not subscriptions:
        await send_telegram_message("📋 <b>Daily Summary (WIB):</b>\n\nTidak ada subscription terdaftar.")
        return

    # Kelompokkan subscription berdasarkan brand
    brand_dict = {}
    for sub in subscriptions:
        brand = sub.brand or "Tidak Dikategorikan" # Jika brand kosong, masukkan ke kategori default
        if brand not in brand_dict:
            brand_dict[brand] = []
        brand_dict[brand].append(sub)

    # Gunakan waktu WIB untuk pengecekan
    today_wib = datetime.now(timezone_wib).date()
    message_lines = [f"📋 <b>Daily Summary ({today_wib.strftime('%d %b %Y, %H:%M')} WIB):</b>"]

    # Urutkan brand secara alfabetis
    for brand in sorted(brand_dict.keys()):
        subs = brand_dict[brand]
        message_lines.append(f"\n<b>{brand}:</b>")
        for sub in subs:
            expires_at = sub.expires_at
            days_left = (expires_at - today_wib).days
            if days_left > 0:
                status = f"{days_left} hari lagi"
            elif days_left == 0:
                status = "<b>Expired HARI INI!</b>"
            else:
                status = f"<b>Expired {abs(days_left)} hari lalu!</b>"

            message_lines.append(
                f"  • <b>{sub.name}</b>\n"
                f"    <code>{sub.url}</code>\n"
                f"    <i>Expired:</i> {expires_at.strftime('%d %b %Y')}\n"
                f"    <i>Sisa Waktu:</i> {status}"
            )

    full_message = "\n".join(message_lines)
    await send_telegram_message(full_message)
