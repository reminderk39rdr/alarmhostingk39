# main.py
import os
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo # Import tambahan
from fastapi import FastAPI, Depends, HTTPException
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from contextlib import asynccontextmanager
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
import secrets

# --- Atur zona waktu default ke WIB ---
timezone_wib = ZoneInfo("Asia/Jakarta")
# --------------------------

from database import engine, SessionLocal, Base
from models import Subscription
from schemas import SubscriptionCreate, Subscription as SubscriptionSchema
from crud import (
    get_subscriptions,
    create_subscription,
    delete_subscription,
    update_subscription,
    get_expiring_soon,
    get_all_subscriptions,
)
from telegram_bot import send_telegram_message, send_daily_summary

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

# Fungsi untuk reminder dinamis (H-3, H-1, H-0) - DENGAN WIB
def run_dynamic_reminders():
    """
    Fungsi utama untuk mengecek semua subscription dan mengatur reminder dinamis.
    Menggunakan zona waktu WIB.
    """
    db = SessionLocal()
    try:
        subscriptions = get_all_subscriptions(db)
        # Gunakan waktu WIB untuk pengecekan
        now_wib = datetime.now(timezone_wib)
        today_wib = now_wib.date()

        for sub in subscriptions:
            expires_at = sub.expires_at

            # --- Cek H-3 Reminder ---
            if expires_at == today_wib + timedelta(days=3):
                if sub.reminder_count_h3 < 2:
                    if sub.reminder_count_h3 == 0:
                        msg = f"🚨 Reminder: '{sub
