from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from contextlib import asynccontextmanager
from apscheduler.schedulers.background import BackgroundScheduler
import asyncio

from database import engine, SessionLocal, Base
from models import Subscription
from schemas import SubscriptionCreate, Subscription as SubscriptionSchema
from crud import get_subscriptions, create_subscription, delete_subscription, get_expiring_soon
from telegram_bot import send_telegram_message

# Buat tabel saat startup
Base.metadata.create_all(bind=engine)

# ✅ PINDAHKAN FUNGSI INI KE ATAS
async def check_and_send_reminders():
    db = SessionLocal()
    try:
        # Cek yang expired dalam 3 hari
        subs_3d = get_expiring_soon(db, 3)
        for sub in subs_3d:
            msg = f"🚨 Reminder: '{sub.name}' ({sub.url}) expires in 3 days! ({sub.expires_at})"
            await send_telegram_message(msg)

        # Cek yang expired besok
        subs_1d = get_expiring_soon(db, 1)
        for sub in subs_1d:
            msg = f"🔥 URGENT: '{sub.name}' ({sub.url}) expires TOMORROW! ({sub.expires_at})"
            await send_telegram_message(msg)
    finally:
        db.close()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Jalankan scheduler
    scheduler = BackgroundScheduler()
    scheduler.add_job(check_and_send_reminders, "cron", hour=9, minute=0)
    scheduler.start()
    print("✅ Scheduler started (daily at 9:00 AM)")
    yield
    scheduler.shutdown()

app = FastAPI(title="K39 Hosting Reminder", lifespan=lifespan)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/subscriptions/", response_model=list[SubscriptionSchema])
def read_subscriptions(db: Session = Depends(get_db)):
    return get_subscriptions(db)

@app.post("/subscriptions/", response_model=SubscriptionSchema)
def create_new_subscription(sub: SubscriptionCreate, db: Session = Depends(get_db)):
    return create_subscription(db, sub)  # ✅ Tidak bentrok

@app.delete("/subscriptions/{sub_id}")
def delete_existing_subscription(sub_id: int, db: Session = Depends(get_db)):
    if not delete_subscription(db, sub_id):  # ✅ Tidak bentrok
        raise HTTPException(status_code=404, detail="Not found")
    return {"ok": True}

@app.get("/trigger")
async def trigger_reminders():
    await check_and_send_reminders()
    return {"status": "Reminders sent"}
