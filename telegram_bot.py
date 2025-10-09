# telegram_bot.py
import os
import httpx

# Ambil dari environment variables (aman untuk Render)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

async def send_telegram_message(text: str):
    """
    Kirim pesan ke Telegram menggunakan bot.
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ TELEGRAM_BOT_TOKEN atau TELEGRAM_CHAT_ID belum di-set di environment variables.")
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
