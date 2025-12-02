# main.py — ALARMHOSTINGK39 FINAL FOREVER EDITION (3 Desember 2025)

import os
import threading
import secrets
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
import re

from fastapi import FastAPI, Depends, HTTPException, Request, Form
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

import asyncio

from database import engine, SessionLocal, Base
from models import Subscription
from crud import get_subscriptions, get_all_subscriptions, create_subscription, update_subscription, delete_subscription
from telegram_bot import send_telegram_message, send_daily_summary

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# =============================================
# DATABASE BOOTSTRAP — PASTIKAN SEMUA KOLOM ADA
# =============================================
Base.metadata.create_all(bind=engine)

with engine.begin() as conn:
    inspector = inspect(engine)
    columns = [col['name'] for col in inspector.get_columns('subscription')]
    
    for col in ['reminder_count_h3', 'reminder_count_h2', 'reminder_count_h1', 'reminder_count_h0']:
        if col not in columns:
            conn.execute(text(f"ALTER TABLE subscription ADD COLUMN {col} INTEGER DEFAULT 0"))

logger.info("Database siap — semua kolom reminder sudah ada. Data lama aman!")

# =============================================
# KONFIGURASI
# =============================================
timezone_wib = ZoneInfo("Asia/Jakarta")
security = HTTPBasic()
templates = Jinja2Templates(directory="templates")

def verify_credentials(credentials: HTTPBasicCredentials = Depends(security)):
    if not (secrets.compare_digest(credentials.username, os.getenv("ADMIN_USERNAME", "admin")) and
            secrets.compare_digest(credentials.password, os.getenv("ADMIN_PASSWORD", "secret"))):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return credentials.username

# =============================================
# INPUT VALIDATION
# =============================================
def validate_input(name: str, url: str, expires_at: str):
    if not name or len(name.strip()) < 2:
        raise HTTPException(status_code=400, detail="Name minimal 2 karakter")
    if not url or not url.strip().lower().startswith(('http://', 'https://')):
        raise HTTPException(status_code=400, detail="URL harus valid dan diawali http/https")
    if not re.match(r"^\d{2}/\d{2}/\d{4}$", expires_at.strip()):
        raise HTTPException(status_code=400, detail="Format tanggal harus mm/dd/yyyy")
    try:
        exp_date = datetime.strptime(expires_at.strip(), "%m/%d/%Y").date()
        if exp_date < datetime.now().date():
            raise HTTPException(status_code=400, detail="Tanggal expire tidak boleh di masa lalu")
    except:
        raise HTTPException(status_code=400, detail="Tanggal tidak valid")
    return name.strip(), url.strip(), exp_date

# =============================================
# TELEGRAM SEND
# =============================================
async def safe_send(msg: str):
    try:
        await send_telegram_message(msg)
    except Exception as e:
        logger.error(f"Telegram error: {e}")

def send_in_thread(msg: str):
    threading.Thread(target=lambda: asyncio.run(safe_send(msg)), daemon=True).start()

# =============================================
# REMINDER ENGINE
# =============================================
def run_dynamic_reminders():
    db = SessionLocal()
    try:
        today = datetime.now(timezone_wib).date()
        for sub in get_all_subscriptions(db):
            days_left = (sub.expires_at - today).days

            # Auto reset saat renew
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

# =============================================
# SCHEDULER
# =============================================
scheduler = BackgroundScheduler(timezone=timezone_wib)
scheduler.add_job(run_dynamic_reminders, "interval", minutes=10)
scheduler.add_job(daily_job, CronTrigger(hour=9, minute=0))
scheduler.start()

# =============================================
# FASTAPI APP
# =============================================
app = FastAPI()

app.mount("/static", StaticFiles(directory="static"))

@app.get("/", response_class=HTMLResponse)
async def root(request: Request, username: str = Depends(verify_credentials)):
    db = SessionLocal()
    subs = get_subscriptions(db)
    db.close()
    return templates.TemplateResponse("index.html", {"request": request, "subs": subs})

@app.post("/add")
async def add(
    username: str = Depends(verify_credentials),
    name: str = Form(...),
    url: str = Form(...),
    brand: str = Form(None),
    expires_at: str = Form(...)
):
    name, url, exp_date = validate_input(name, url, expires_at)
    db = SessionLocal()
    create_subscription(db, SubscriptionCreate(name=name, url=url, expires_at=exp_date, brand=brand.strip() if brand else None))
    db.close()
    return RedirectResponse(url="/", status_code=303)

@app.post("/update/{sub_id}")
async def update(
    sub_id: int,
    username: str = Depends(verify_credentials),
    name: str = Form(...),
    url: str = Form(...),
    brand: str = Form(None),
    expires_at: str = Form(...)
):
    name, url, exp_date = validate_input(name, url, expires_at)
    db = SessionLocal()
    update_subscription(db, sub_id, SubscriptionCreate(name=name, url=url, expires_at=exp_date, brand=brand.strip() if brand else None))
    db.close()
    return RedirectResponse(url="/", status_code=303)

@app.post("/delete/{sub_id}")
async def delete(sub_id: int, username: str = Depends(verify_credentials)):
    db = SessionLocal()
    delete_subscription(db, sub_id)
    db.close()
    return RedirectResponse(url="/", status_code=303)

@app.get("/trigger")
async def trigger(username: str = Depends(verify_credentials)):
    run_dynamic_reminders()
    daily_job()
    return {"status": "Reminder manual terkirim"}

@app.get("/keep-alive")
async def keep_alive():
    return {"status": "ALIVE FOREVER — POSTGRESQL + VALIDATION + H-2 AKTIF", "time": datetime.now(timezone_wib).isoformat()}
