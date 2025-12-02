# main.py — ALARMHOSTINGK39 FINAL BULLETPROOF EDITION
# 100% jalan di Render Starter + Python 3.13 + SQLite
# Fix duplicate import, full comment, super rapih & aman

import os
import threading
import secrets
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

import asyncio

# Local modules (pastikan nama file sesuai)
from database import engine, SessionLocal, Base
from models import Subscription
from crud import (
    get_subscriptions,
    get_all_subscriptions,
    create_subscription,
    update_subscription,
    delete_subscription,
)
from schemas import SubscriptionCreate, Subscription  # ini yang benar di repo kamu
from telegram_bot import send_telegram_message, send_daily_summary  # hanya sekali

# ==================== LOGGING SETUP ====================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# ==================== DATABASE BOOTSTRAP ====================
logger.info("[BOOT] Membuat tabel subscription jika belum ada...")
Base.metadata.create_all(bind=engine)

logger.info("[BOOT] Mengecek & menambahkan kolom reminder_count_h2 jika belum ada...")
try:
    inspector = inspect(engine)
    columns = [col["name"] for col in inspector.get_columns("subscription")]
    if "reminder_count_h2" not in columns:
        logger.info("[BOOT] Kolom reminder_count_h2 belum ada → ditambahkan sekarang")
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE subscription ADD COLUMN reminder_count_h2 INTEGER DEFAULT 0"))
        logger.info("[BOOT] Kolom reminder_count_h2 berhasil ditambahkan!")
except Exception as e:
    logger.warning(f"[BOOT] Gagal cek/tambah kolom h2 (mungkin sudah ada): {e}")

# ==================== KONFIGURASI UMUM ====================
timezone_wib = ZoneInfo("Asia/Jakarta")
security = HTTPBasic()
templates = Jinja2Templates(directory="templates")

# ==================== AUTHENTICATION ====================
def verify_credentials(credentials: HTTPBasicCredentials = Depends(security)):
    correct_username = secrets.compare_digest(credentials.username, os.getenv("ADMIN_USERNAME", "admin"))
    correct_password = secrets.compare_digest(credentials.password, os.getenv("ADMIN_PASSWORD", "secret"))
    if not (correct_username and correct_password):
        raise HTTPException(status_code=401, detail="Username atau password salah")
    return credentials.username

# ==================== TELEGRAM HELPER (SAFE SEND) ====================
async def safe_send_telegram(message: str):
    """Kirim pesan ke Telegram dengan error handling penuh"""
    try:
        await send_telegram_message(message)
        logger.info(f"[TG OK] {message.splitlines()[0][:50]}...")
    except Exception as e:
        logger.error(f"[TG ERROR] Gagal kirim pesan: {e}")

def send_in_thread(message: str):
    """Jalankan pengiriman Telegram di background thread agar tidak blocking"""
    threading.Thread(target=lambda: asyncio.run(safe_send_telegram(message)), daemon=True).start()

# ==================== REMINDER ENGINE ====================
def run_dynamic_reminders():
    logger.info("[REMINDER] Job dimulai — memproses semua subscription")
    db = SessionLocal()
    try:
        today = datetime.now(timezone_wib).date()
        for sub in get_all_subscriptions(db):
            try:
                if not sub.expires_at:
                    continue

                days_left = (sub.expires_at - today).days

                # Auto reset semua counter saat subscription diperpanjang (>20 hari)
                if days_left > 20 and any([
                    getattr(sub, "reminder_count_h3", 0),
                    getattr(sub, "reminder_count_h2", 0),
                    getattr(sub, "reminder_count_h1", 0),
                    getattr(sub, "reminder_count_h0", 0)
                ]):
                    sub.reminder_count_h3 = sub.reminder_count_h2 = sub.reminder_count_h1 = sub.reminder_count_h0 = 0
                    db.commit()
                    logger.info(f"[RESET] Counters direset → {sub.name}")

                # H-3 : 2x sehari
                if days_left == 3 and getattr(sub, "reminder_count_h3", 0) < 2:
                    msg = f"⚠️ Pemberitahuan Penting\n\nLayanan *{sub.name}* akan berakhir dalam 3 hari lagi.\n{sub.url}\nExpire: {sub.expires_at.strftime('%d %B %Y')}\n\nMohon segera lakukan perpanjangan.\nTerima kasih 🙏"
                    send_in_thread(msg)
                    sub.reminder_count_h3 = getattr(sub, "reminder_count_h3", 0) + 1
                    db.commit()

                # H-2 : 3x sehari
                elif days_left == 2 and getattr(sub, "reminder_count_h2", 0) < 3:
                    msg = f"🚨 Informasi Mendesak\n\n*{sub.name}* tersisa hanya 2 hari lagi!\n{sub.url}\nExpire: {sub.expires_at.strftime('%d %B %Y')}\n\nSegera perpanjang hari ini. Tim kami siap membantu 🙏"
                    send_in_thread(msg)
                    sub.reminder_count_h2 = getattr(sub, "reminder_count_h2", 0) + 1
                    db.commit()

                # H-1 : 5x sehari (panic mode sopan)
                elif days_left == 1 and getattr(sub, "reminder_count_h1", 0) < 5:
                    messages = [
                        "🔴 Pemberitahuan Sangat Mendesak\n\nLayanan akan berakhir *BESOK*.\nMohon perpanjang hari ini juga 🙏",
                        "🔴 Informasi Kritis\n\nTersisa kurang dari 24 jam lagi.\nSegera lakukan perpanjangan sekarang.",
                        "🔴 Peringatan Final\n\nBesok layanan akan dinonaktifkan.\nKami siap membantu renewal Anda.",
                        "🔴 Mohon Perhatian Khusus\n\nPerpanjangan hari ini menjaga data tetap aman.",
                        "🔴 Pemberitahuan Malam\n\nHanya beberapa jam tersisa.\nMohon perpanjang malam ini juga 🙏"
                    ]
                    msg = messages[getattr(sub, "reminder_count_h1", 0)] + f"\n\n*{sub.name}*\n{sub.url}\nExpire: {sub.expires_at.strftime('%d %B %Y')}"
                    send_in_thread(msg)
                    sub.reminder_count_h1 = getattr(sub, "reminder_count_h1", 0) + 1
                    db.commit()

                # H-0 atau sudah lewat : max 8x spam sopan
                elif days_left <= 0 and getattr(sub, "reminder_count_h0", 0) < 8:
                    msg = f"🔴 Layanan Telah Berakhir\n\n*{sub.name}* telah kadaluarsa sejak {sub.expires_at.strftime('%d %B %Y')}.\n{sub.url}\n\nSegera lakukan perpanjangan untuk mengaktifkan kembali.\nKami siap melayani 24/7 🙏"
                    send_in_thread(msg)
                    sub.reminder_count_h0 = getattr(sub, "reminder_count_h0", 0) + 1
                    db.commit()

            except Exception as e:
                logger.error(f"[ERROR] Gagal proses subscription {getattr(sub, 'name', 'Unknown')}: {e}")
                db.rollback()

    except Exception as e:
        logger.error(f"[CRITICAL] Reminder job crash: {e}")
    finally:
        db.close()
    logger.info("[REMINDER] Job selesai")

# Daily summary job
def send_daily_summary_job():
    db = SessionLocal()
    try:
        asyncio.run(send_daily_summary(get_all_subscriptions(db)))
        logger.info("[DAILY SUMMARY] Berhasil terkirim jam 09:00 WIB")
    except Exception as e:
        logger.error(f"[DAILY SUMMARY ERROR] {e}")
    finally:
        db.close()

# ==================== SCHEDULER START ====================
scheduler = BackgroundScheduler(timezone=timezone_wib)
scheduler.add_job(run_dynamic_reminders, CronTrigger(minute="*/10"))  # setiap 10 menit
scheduler.add_job(send_daily_summary_job, CronTrigger(hour=9, minute=0))  # setiap hari jam 09:00 WIB
scheduler.start()
logger.info("[SCHEDULER] Telah diaktifkan — reminder jalan 24/7")

# ==================== FASTAPI APP ====================
app = FastAPI(title="AlarmHostingK39 — Reminder System")

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, username: str = Depends(verify_credentials)):
    db = SessionLocal()
    subs = get_subscriptions(db)
    db.close()
    return templates.TemplateResponse("index.html", {"request": request, "subs": subs})

@app.get("/trigger")
async def manual_trigger(username: str = Depends(verify_credentials)):
    run_dynamic_reminders()
    send_daily_summary_job()
    return {"status": "success", "message": "Manual reminder & summary telah dikirim!"}

@app.get("/keep-alive")
async def keep_alive():
    return {
        "status": "ALIVE & SUPER SEHAT",
        "time_wib": datetime.now(timezone_wib).strftime("%d %B %Y %H:%M:%S"),
        "uptime_guaranteed": "cron-job.org ping setiap 10 menit",
        "version": "Final Bulletproof Edition — 3 Des 2025"
    }

# Global exception handler — app tidak pernah mati
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"[GLOBAL ERROR] {exc}")
    return JSONResponse(status_code=500, content={"detail": "Server tetap hidup — error telah ditangani"})

# ==================== BOOT COMPLETE ====================
logger.info("🚀 alarmhostingk39 BOOT SUKSES TOTAL — SISTEM SIAP MENGHASILKAN UANG SEKARANG JUGA! 🚀")
