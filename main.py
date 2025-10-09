# main.py
import os
from fastapi import FastAPI, Depends, HTTPException
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from contextlib import asynccontextmanager
from apscheduler.schedulers.background import BackgroundScheduler
import secrets
from datetime import date, timedelta

from database import engine, SessionLocal, Base
from models import Subscription
from schemas import SubscriptionCreate, Subscription as SubscriptionSchema
from crud import (
    get_subscriptions,
    create_subscription,
    delete_subscription,
    update_subscription,
    get_expiring_soon,
)
from telegram_bot import send_telegram_message

# Buat tabel saat startup
Base.metadata.create_all(bind=engine)

# HTTP Basic Auth
security = HTTPBasic()

def verify_credentials(credentials: HTTPBasicCredentials = Depends(security)):
    correct_user = secrets.compare_digest(
        credentials.username, os.getenv("ADMIN_USERNAME", "admin")
    )
    correct_pass = secrets.compare_digest(
        credentials.password, os.getenv("ADMIN_PASSWORD", "secret")
    )
    if not (correct_user and correct_pass):
        raise HTTPException(
            status_code=401,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

# Scheduler logic
async def check_and_send_reminders():
    db = SessionLocal()
    try:
        # Cek H-3
        subs_3d = get_expiring_soon(db, 3)
        for sub in subs_3d:
            msg = f"🚨 Reminder: '{sub.name}' ({sub.url}) expires in 3 days! ({sub.expires_at})"
            await send_telegram_message(msg)

        # Cek H-1
        subs_1d = get_expiring_soon(db, 1)
        for sub in subs_1d:
            msg = f"🔥 URGENT: '{sub.name}' ({sub.url}) expires TOMORROW! ({sub.expires_at})"
            await send_telegram_message(msg)

        # Cek Hari Ini (opsional)
        subs_0d = get_expiring_soon(db, 0)
        for sub in subs_0d:
            msg = f"💥 EXPIRED TODAY: '{sub.name}' ({sub.url}) expires TODAY! ({sub.expires_at})"
            await send_telegram_message(msg)

    except Exception as e:
        print(f"🚨 Error saat scheduler: {e}")
    finally:
        db.close()

@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = BackgroundScheduler()
    scheduler.add_job(check_and_send_reminders, "cron", hour=9, minute=0)
    scheduler.start()
    print("✅ Scheduler started (daily at 9:00 AM)")
    yield
    scheduler.shutdown()

app = FastAPI(title="K39 Hosting Reminder", lifespan=lifespan)

# Serve static files (UI Admin)
app.mount("/static", StaticFiles(directory="static"), name="static")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def root(username: str = Depends(verify_credentials)):
    return RedirectResponse("/static/index.html")

@app.get("/subscriptions/", response_model=list[SubscriptionSchema])
def read_subscriptions(db: Session = Depends(get_db), username: str = Depends(verify_credentials)):
    return get_subscriptions(db)

@app.post("/subscriptions/", response_model=SubscriptionSchema)
def create_new_subscription(
    sub: SubscriptionCreate,
    db: Session = Depends(get_db),
    username: str = Depends(verify_credentials)
):
    return create_subscription(db, sub)

@app.put("/subscriptions/{sub_id}", response_model=SubscriptionSchema)
def update_existing_subscription(
    sub_id: int,
    sub: SubscriptionCreate,
    db: Session = Depends(get_db),
    username: str = Depends(verify_credentials)
):
    updated = update_subscription(db, sub_id, sub)
    if not updated:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return updated

@app.delete("/subscriptions/{sub_id}")
def delete_existing_subscription(
    sub_id: int,
    db: Session = Depends(get_db),
    username: str = Depends(verify_credentials)
):
    deleted = delete_subscription(db, sub_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Not found")
    return {"ok": True}

@app.get("/trigger")
async def trigger_reminders(username: str = Depends(verify_credentials)):
    await check_and_send_reminders()
    return {"status": "Reminders sent"}
