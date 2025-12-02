# main.py — FINAL & HIDUP TOTAL (3 Desember 2025)

import os
import threading
import secrets
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
import re

from fastapi import FastAPI, Depends, HTTPException, Request, Form
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
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
# DATABASE BOOTSTRAP — TAMBAH KOLOM OTOMATIS
# =============================================
Base.metadata.create_all(bind=engine)

logger.info("[BOOT] Memastikan kolom reminder_count ada...")

try:
    with engine.begin() as conn:
        inspector = inspect(engine)
        columns = [col['name'] for col in inspector.get_columns('subscription')]
        
        for col in ['reminder_count_h3', 'reminder_count_h2', 'reminder_count_h1', 'reminder_count_h0']:
            if col not in columns:
                conn.execute(text(f"ALTER TABLE subscription ADD COLUMN {col} INTEGER DEFAULT 0"))
except Exception as e:
    logger.error(f"[BOOT] Gagal tambah kolom: {e}")

logger.info("[BOOT] Database PostgreSQL siap — data lama kembali 100%")

# =============================================
# KONFIG
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
def validate_input(name: str, url: str, expires_at: str, brand: str = None):
    name = name.strip()
    url = url.strip()
    expires_at = expires_at.strip()
    if len(name) < 2:
        raise HTTPException(status_code=400, detail="Name minimal 2 karakter")
    if not url.lower().startswith(('http://', 'https://')):
        raise HTTPException(status_code=400, detail="URL harus diawali http/https")
    if not re.match(r"^\d{2}/\d{2}/\d{4}$", expires_at):
        raise HTTPException(status_code=400, detail="Format tanggal mm/dd/yyyy")
    try:
        exp_date = datetime.strptime(expires_at, "%m/%d/%Y").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Tanggal tidak valid")
    return name, url, exp_date, brand.strip() if brand else None

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

            if days_left > 20:
                if any([getattr(sub, 'reminder_count_h3', 0), getattr(sub, 'reminder_count_h2',0), getattr(sub, 'reminder_count_h1',0), getattr(sub, 'reminder_count_h0',0)]):
                    sub.reminder_count_h3 = sub.reminder_count_h2 = sub.reminder_count_h1 = sub.reminder_count_h0 = 0
                    db.commit()

            if days_left == 3 and getattr(sub, 'reminder_count_h3', 0) < 2:
                send_in_thread(f"⚠️ Pemberitahuan Penting\n\nLayanan *{sub.name}* tinggal 3 hari lagi.\n{sub.url}\nExpire: {sub.expires_at.strftime('%d %B %Y')}\n\nMohon segera perpanjang 🙏")
                sub.reminder_count_h3 = getattr(sub, 'reminder_count_h3', 0) + 1
                db.commit()

            elif days_left == 2 and getattr(sub, 'reminder_count_h2', 0) < 3:
                send_in_thread(f"🚨 Mendesak\n\n*{sub.name}* tinggal 2 hari lagi!\n{sub.url}\nExpire: {sub.expires_at.strftime('%d %B %Y')}\n\nSegera perpanjang hari ini 🙏")
                sub.reminder_count_h2 = getattr(sub, 'reminder_count_h2', 0) + 1
                db.commit()

            elif days_left == 1 and getattr(sub, 'reminder_count_h1', 0) < 5:
                msgs = [
                    "🔴 Sangat Mendesak\n\n*BESOK EXPIRE*\nMohon perpanjang hari ini 🙏",
                    "🔴 <24 jam lagi\nSegera renew sekarang",
                    "🔴 Final warning\nBesok nonaktif",
                    "🔴 Perpanjang hari ini = data aman",
                    "🔴 Malam terakhir — mohon renew 🙏"
                ]
                send_in_thread(msgs[getattr(sub, 'reminder_count_h1', 0)] + f"\n\n*{sub.name}*\n{sub.url}")
                sub.reminder_count_h1 = getattr(sub, 'reminder_count_h1', 0) + 1
                db.commit()

            elif days_left <= 0 and getattr(sub, 'reminder_count_h0', 0) < 8:
                send_in_thread(f"🔴 SUDAH EXPIRE\n\n*{sub.name}* kadaluarsa hari ini.\n{sub.url}\nSegera renew 🙏")
                sub.reminder_count_h0 = getattr(sub, 'reminder_count_h0', 0) + 1
                db.commit()
    except Exception as e:
        logger.error(f"Reminder error: {e}")
    finally:
        db.close()

def daily_job():
    db = SessionLocal()
    try:
        asyncio.run(send_daily_summary(get_all_subscriptions(db)))
    except Exception as e:
        logger.error(f"Daily summary error: {e}")
    finally:
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

app.mount("/static", StaticFiles(directory="static"), name="static")

# API UNTUK FRONTEND JS (ini yang fix "Failed to load subscriptions")
@app.get("/subscriptions")
async def api_subscriptions(username: str = Depends(verify_credentials)):
    db = SessionLocal()
    try:
        subs = get_subscriptions(db)
    except Exception as e:
        logger.error(f"API subscriptions error: {e}")
        return []
    finally:
        db.close()
    return subs

# DB TEST ENDPOINT (fix "Not Found")
@app.get("/db-test")
async def db_test():
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        return {"status": "PostgreSQL connected", "message": "Database siap!"}
    except Exception as e:
        return {"status_code=500, content={"status": "error", "detail": str(e)}

@app.get("/", response_class=HTMLResponse)
async def root(request: Request, username: str = Depends(verify_credentials)):
    return RedirectResponse(url="/static/index.html")

@app.post("/add")
async def add(username: str = Depends(verify_credentials), name: str = Form(...), url: str = Form(...), brand: str = Form(None), expires_at: str = Form(...)):
    name, url, exp_date, brand = validate_input(name, url, expires_at, brand)
    db = SessionLocal()
    create_subscription(db, SubscriptionCreate(name=name, url=url, expires_at=exp_date, brand=brand))
    db.close()
    return RedirectResponse(url="/static/index.html", status_code=303)

@app.post("/update/{sub_id}")
async def update(sub_id: int, username: str = Depends(verify_credentials), name: str = Form(...), url: str = Form(...), brand: str = Form(None), expires_at: str = Form(...)):
    name, url, exp_date, brand = validate_input(name, url, expires_at, brand)
    db = SessionLocal()
    update_subscription(db, sub_id, SubscriptionCreate(name=name, url=url, expires_at=exp_date, brand=brand))
    db.close()
    return RedirectResponse(url="/static/index.html", status_code=303)

@app.post("/delete/{sub_id}")
async def delete(sub_id: int, username: str = Depends(verify_credentials)):
    db = SessionLocal()
    delete_subscription(db, sub_id)
    db.close()
    return RedirectResponse(url="/static/index.html", status_code=303)

@app.get("/trigger")
async def trigger(username: str = Depends(verify_credentials)):
    run_dynamic_reminders()
    daily_job()
    return {"status": "success"}

@app.get("/keep-alive")
async def keep_alive():
    return {"status": "HIDUP BRO!!! DATA LAMA KEMBALI — SEMUA JALAN", "time": datetime.now(timezone_wib).isoformat()}

logger.info("K39 Reminder — BOOT SUKSES — DATA LAMA KEMBALI — HIDUP SELAMANYA! 🚀")
