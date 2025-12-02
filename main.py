# main.py - VERSI FINAL 1000% JALAN DI RENDER (3 Desember 2025)
# Tested & hijau di Render Starter + full error handling + keep-alive

import os
import threading
import secrets
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Depends, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.exceptions import RequestValidationError

from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

import asyncio
import httpx

from database import engine, SessionLocal, Base
from models import Subscription
from crud import get_subscriptions, get_all_subscriptions, create_subscription, update_subscription, delete_subscription
from schemas import SubscriptionCreate, SubscriptionSchema
from telegram_bot import send_telegram_message, send_daily_summary

# ==================== LOGGING ====================
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
logger = logging.getLogger(__name__)

# ==================== BOOT FIX (WAJIB URUTAN INI) ====================
logger.info("[BOOT] Membuat tabel...")
Base.metadata.create_all(bind=engine)
logger.info("[BOOT] Tabel siap")

logger.info("[BOOT] Cek kolom reminder_count_h2...")
try:
    inspector = inspect(engine)
    columns = [c['name'] for c in inspector.get_columns('subscription')]
    if 'reminder_count_h2' not in columns:
        logger.info("[BOOT] Tambah kolom reminder_count_h2...")
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE subscription ADD COLUMN reminder_count_h2 INTEGER DEFAULT 0"))
        logger.info("[BOOT] Kolom berhasil ditambah!")
except Exception as e:
    logger.error(f"[BOOT] Gagal tambah kolom (tidak fatal): {e}")

# ==================== SETUP ====================
timezone_wib = ZoneInfo("Asia/Jakarta")
security = HTTPBasic()
templates = Jinja2Templates(directory="templates")

def verify_credentials(credentials: HTTPBasicCredentials = Depends(security)):
    correct_user = secrets.compare_digest(credentials.username, os.getenv("ADMIN_USERNAME", "admin"))
    correct_pass = secrets.compare_digest(credentials.password, os.getenv("ADMIN_PASSWORD", "secret"))
    if not (correct_user and correct_pass):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return credentials.username

# ==================== TELEGRAM SAFE SEND ====================
async def safe_send_telegram(msg: str):
    try:
        await send_telegram_message(msg)
    except Exception as e:
        logger.error(f"[TELEGRAM ERROR] {e}")

def send_in_thread(msg: str):
    threading.Thread(target=lambda: asyncio.run(safe_send_telegram(msg)), daemon=True).start()

# ==================== REMINDER JOB (SUPER STABIL) ====================
def run_dynamic_reminders():
    logger.info("[JOB] Reminder dimulai")
    db = SessionLocal()
    try:
        subs = get_all_subscriptions(db)
        today = datetime.now(timezone_wib).date()

        for sub in subs:
            try:
                if not sub.expires_at: continue
                days_left = (sub.expires_at - today).days

                # Auto reset counter
                if days_left > 20 and any([sub.reminder_count_h3, sub.reminder_count_h2, sub.reminder_count_h1, sub.reminder_count_h0]):
                    sub.reminder_count_h3 = sub.reminder_count_h2 = sub.reminder_count_h1 = sub.reminder_count_h0 = 0
                    db.commit()

                if days_left == 3 and sub.reminder_count_h3 < 2:
                    msg = f"⚠️ Pemberitahuan Penting\n\nLayanan *{sub.name}* akan berakhir dalam 3 hari.\n{sub.url}\nExpire: {sub.expires_at.strftime('%d %B %Y')}\n\nMohon segera perpanjang. Terima kasih 🙏"
                    send_in_thread(msg)
                    sub.reminder_count_h3 += 1
                    db.commit()

                elif days_left == 2 and sub.reminder_count_h2 < 3:
                    msg = f"🚨 Informasi Mendesak\n\n*{sub.name}* tinggal 2 hari lagi.\n{sub.url}\nExpire: {sub.expires_at.strftime('%d %B %Y')}\n\nSegera perpanjang hari ini. Tim siap membantu 🙏"
                    send_in_thread(msg)
                    sub.reminder_count_h2 += 1
                    db.commit()

                elif days_left == 1 and sub.reminder_count_h1 < 5:
                    msgs = [
                        "🔴 Pemberitahuan Sangat Mendesak\n\nLayanan akan berakhir *BESOK*.\nMohon perpanjang hari ini juga 🙏",
                        "🔴 Informasi Kritis\n\nTersisa < 24 jam lagi.\nSegera lakukan perpanjangan sekarang.",
                        "🔴 Peringatan Final\n\nBesok layanan akan nonaktif.\nKami siap bantu renewal Anda.",
                        "🔴 Mohon Perhatian Khusus\n\nPerpanjangan hari ini menjaga data tetap aman.",
                        "🔴 Pemberitahuan Malam\n\nBeberapa jam tersisa.\nMohon perpanjang malam ini juga 🙏"
                    ]
                    msg = msgs[sub.reminder_count_h1] + f"\n\n*{sub.name}*\n{sub.url}\nExpire: {sub.expires_at.strftime('%d %B %Y')}"
                    send_in_thread(msg)
                    sub.reminder_count_h1 += 1
                    db.commit()

                elif days_left <= 0 and sub.reminder_count_h0 < 8:
                    msg = f"🔴 Layanan Telah Berakhir\n\n*{sub.name}* kadaluarsa tanggal {sub.expires_at.strftime('%d %B %Y')}.\n{sub.url}\n\nSegera perpanjang untuk aktivasi kembali.\nKami siap 24/7 🙏"
                    send_in_thread(msg)
                    sub.reminder_count_h0 += 1
                    db.commit()

            except Exception as e:
                logger.error(f"[SUB ERROR] {sub.name}: {e}")
                db.rollback()

    except Exception as e:
        logger.error(f"[JOB ERROR] {e}")
    finally:
        db.close()

def send_daily_summary_job():
    db = SessionLocal()
    try:
        subs = get_all_subscriptions(db)
        asyncio.run(send_daily_summary(subs))
    except Exception as e:
        logger.error(f"[DAILY ERROR] {e}")
    finally:
        db.close()

# ==================== SCHEDULER ====================
scheduler = BackgroundScheduler(timezone=timezone_wib)
scheduler.add_job(run_dynamic_reminders, CronTrigger(minute="*/10"))
scheduler.add_job(send_daily_summary_job, CronTrigger(hour=9, minute=0))
scheduler.start()
logger.info("[SCHEDULER] Aktif 24/7")

# ==================== FASTAPI APP ====================
app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/", response_class=HTMLResponse)
async def root(request: Request, username: str = Depends(verify_credentials)):
    db = SessionLocal()
    subs = get_subscriptions(db)
    db.close()
    return templates.TemplateResponse("index.html", {"request": request, "subs": subs})

@app.get("/trigger")
async def trigger(username: str = Depends(verify_credentials)):
    run_dynamic_reminders()
    send_daily_summary_job()
    return {"status": "Manual trigger sukses"}

@app.get("/keep-alive")
async def keep_alive():
    return {
        "status": "ALIVE & BULLETPROOF",
        "time": datetime.now(timezone_wib).strftime("%d %B %Y %H:%M:%S WIB"),
        "next_daily": "09:00 WIB setiap hari",
        "message": "Deploy ini sekarang juga – 100% hijau!"
    }

# Global error handler (app ga mati pernah lagi)
@app.exception_handler(Exception)
async def global_handler(request: Request, exc: Exception):
    logger.error(f"[GLOBAL ERROR] {exc}")
    return JSONResponse(status_code=500, content={"detail": "Server stabil – error sudah dilog"})

logger.info("[BOOT COMPLETE] alarmhostingk39 SIAP PAKAI 100% – DEPLOY SEKARANG BRO!")
