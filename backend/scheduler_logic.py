from sqlalchemy.orm import Session
from . import crud, telegram_bot

async def check_and_send_reminders(db: Session):
    # Cek yang expired dalam 3 hari
    subs_3d = crud.get_expiring_soon(db, 3)
    for sub in subs_3d:
        msg = f"🚨 Reminder: '{sub.name}' ({sub.url}) expires in 3 days! ({sub.expires_at})"
        await telegram_bot.send_telegram_message(msg)

    # Cek yang expired besok
    subs_1d = crud.get_expiring_soon(db, 1)
    for sub in subs_1d:
        msg = f"🔥 URGENT: '{sub.name}' ({sub.url}) expires TOMORROW! ({sub.expires_at})"
        await telegram_bot.send_telegram_message(msg)