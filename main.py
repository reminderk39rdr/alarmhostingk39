# main.py — ALARMHOSTINGK39 FINAL PRODUCTION READY

import os
import threading
import secrets
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

import asyncio

from database import engine, SessionLocal, Base
from models import Subscription
from crud import get_subscriptions, get_all_subscriptions
from telegram_bot import send_telegram_message, send_daily_summary

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Buat tabel + tambah kolom reminder kalau belum ada (POSTGRESQL SAFE)
Base.metadata.create_all(bind=engine)

try:
    inspector = inspect(engine)
    columns = {c["name"] for c in inspector.get_columns("subscription")}
    for col in ["reminder_count_h3", "reminder_count_h2", "reminder_count_h1", "reminder_count_h0"]:
        if col not in columns:
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE subscription ADD COLUMN {col} INTEGER DEFAULT 0"))
except Exception as e:
    logger.warning(f"Kolom reminder gagal ditambah (mungkin sudah ada): {e}")

# Konfigurasi
timezone_wib = ZoneInfo("Asia/Jakarta")
security = HTTPBasic()
templates = Jinja2Templates(directory="templates")

def verify_credentials(credentials: HTTPBasicCredentials = Depends(security)):
    if not (secrets.compare_digest(credentials.username, os.getenv("ADMIN_USERNAME", "admin")) and
            secrets.compare_digest(credentials.password, os.getenv("ADMIN_PASSWORD", "secret"))):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return credentials.username

# Telegram safe send
async def safe_send(msg: str):
    try:
        await send_telegram_message(msg)
    except:
        pass

def send_in_thread(msg: str):
    threading.Thread(target=lambda: asyncio.run(safe_send(msg)), daemon=True).start()

# Reminder engine
def run_dynamic_reminders():
    db = SessionLocal()
    try:
        today = datetime.now(timezone_wib).date()
        for sub in get_all_subscriptions(db):
            days_left = (sub.expires_at - today).days

            if days_left > 20:
                if any([sub.reminder_count_h3, sub.reminder_count_h2, sub.reminder_count_h1, sub.reminder_count_h0]):
                    sub.reminder_count_h3 = sub.reminder_count_h2 = sub.reminder_count_h1 = sub.reminder_count_h0 = 0
                    db.commit()

            if days_left == 3 and sub.reminder_count_h3 < 2:
                send_in_thread(f"⚠️ Pemberitahuan Penting\n\nLayanan *{sub.name}* tinggal 3 hari lagi.\n{sub.url}\nExpire: {sub.expires_at.strftime('%d %B %Y')}\n\nMohon segera perpanjang 🙏")
                sub.reminder_count_h3 += 1
                db.commit()

            elif days_left == 2 and sub.reminder_count_h2 < 3:
                send_in_thread(f"🚨 Mendesak\n\n*{sub.name}* tinggal 2 hari lagi!\n{sub.url}\nExpire: {sub.expires_at.strftime('%d %B %Y')}\n\nSegera perpanjang hari ini 🙏")
                sub.reminder_count_h2 += 1
                db.commit()

            elif days_left == 1 and sub.reminder_count_h1 < 5:
                msgs = [
                    "🔴 Sangat Mendesak\n\n*BESOK EXPIRE*\nMohon perpanjang hari ini 🙏",
                    "🔴 <24 jam lagi\nSegera renew sekarang",
                    "🔴 Final warning\nBesok nonaktif",
                    "🔴 Perpanjang hari ini = data aman",
                    "🔴 Malam terakhir — mohon renew 🙏"
                ]
                send_in_thread(msgs[sub.reminder_count_h1] + f"\n\n*{sub.name}*\n{sub.url}")
                sub.reminder_count_h1 += 1
                db.commit()

            elif days_left <= 0 and sub.reminder_count_h0 < 8:
                send_in_thread(f"🔴 SUDAH EXPIRE\n\n*{sub.name}* kadaluarsa hari ini.\n{sub.url}\nSegera renew 🙏")
                sub.reminder_count_h0 += 1
                db.commit()
    finally:
        db.close()

def daily_job():
    db = SessionLocal()
    asyncio.run(send_daily_summary(get_all_subscriptions(db)))
    db.close()

# Scheduler
scheduler = BackgroundScheduler(timezone=timezone_wib)
scheduler.add_job(run_dynamic_reminders, "interval", minutes=10)
scheduler.add_job(daily_job, CronTrigger(hour=9, minute=0))
scheduler.start()

# App
app = FastAPI()

app.mount("/static", StaticFiles(directory="static"))

@app.get("/", response_class=HTMLResponse)
async def root(request: Request, username: str = Depends(verify_credentials)):
    db = SessionLocal()
    subs = get_subscriptions(db)
    db.close()
    return templates.TemplateResponse("index.html", {"request": request, "subs": subs})

@app.get("/trigger")
async def trigger(username: str = Depends(verify_credentials)):
    run_dynamic_reminders()
    daily_job()
    return {"status": "Reminder terkirim"}

@app.get("/keep-alive")
async def keep_alive():
    return {"status": "POSTGRESQL + PERMANENT + FULL REMINDER AKTIF", "time": datetime.now(timezone_wib).isoformat()}
