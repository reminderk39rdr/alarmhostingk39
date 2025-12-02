import os
import httpx
import logging

logger = logging.getLogger(__name__)

async def send_telegram_message(text: str):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        logger.error("TOKEN/CHAT_ID kosong!")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }

    # TRIK KHUSUS RENDER WORK 100%
    headers = {"Content-Type": "application/json"}
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(url, data=payload, headers=headers)
            if r.status_code == 200 and r.json().get("ok"):
                logger.info("Telegram TERKIRIM BRO!")
                return True
            else:
                logger.error(f"Telegram gagal: {r.text}")
    except Exception as e:
        logger.error(f"Telegram error: {e}")
    return False