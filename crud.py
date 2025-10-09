# crud.py
from sqlalchemy.orm import Session
from datetime import date, timedelta
from models import Subscription
from schemas import SubscriptionCreate
from telegram_bot import send_telegram_message

def get_subscriptions(db: Session, skip: int = 0, limit: int = 100):
    return db.query(Subscription).offset(skip).limit(limit).all()

def create_subscription(db: Session, subscription: SubscriptionCreate):
    db_sub = Subscription(**subscription.model_dump())
    db.add(db_sub)
    db.commit()
    db.refresh(db_sub)

    # --- Tambahkan bagian ini ---
    # Cek apakah subscription baru ini jatuh tempo dalam 1 atau 3 hari ke depan
    today = date.today()
    if db_sub.expires_at == today + timedelta(days=1):
        msg = f"🔥 URGENT: '{db_sub.name}' ({db_sub.url}) expires TOMORROW! ({db_sub.expires_at})"
        import asyncio
        # Karena send_telegram_message async, kita perlu cara untuk memanggilnya
        # Di lingkungan sync seperti ini, kita bisa gunakan asyncio.run (jika di luar FastAPI request context)
        # Tapi karena ini dijalankan dari FastAPI, lebih baik kita kirim ke event loop
        # Solusi paling aman: buat fungsi sync untuk mengirim
        # Tapi untuk sementara, kita gunakan asyncio.run
        # Peringatan: asyncio.run bisa membuka event loop baru, tidak efisien jika sering dipanggil
        # Solusi terbaik: buat background task di FastAPI
        import threading
        def run_async():
            import asyncio
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(send_telegram_message(msg))
            finally:
                loop.close()
        thread = threading.Thread(target=run_async)
        thread.start()
    elif db_sub.expires_at == today + timedelta(days=3):
        msg = f"🚨 Reminder: '{db_sub.name}' ({db_sub.url}) expires in 3 days! ({db_sub.expires_at})"
        import threading
        def run_async():
            import asyncio
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(send_telegram_message(msg))
            finally:
                loop.close()
        thread = threading.Thread(target=run_async)
        thread.start()
    # --------------------------

    return db_sub

def delete_subscription(db: Session, subscription_id: int):
    db_sub = db.query(Subscription).filter(Subscription.id == subscription_id).first()
    if db_sub:
        db.delete(db_sub)
        db.commit()
    return db_sub

def get_expiring_soon(db: Session, days_ahead: int):
    target_date = date.today() + timedelta(days=days_ahead)
    return db.query(Subscription).filter(Subscription.expires_at == target_date).all()
