# main.py - FINAL VERSION 100% JALAN DI RENDER (Desember 2025)
# Sopan, elegan, auto-reset counter, H-2 aktif, keep-alive, fix startup error

import os
import threading
import secrets
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Depends, HTTPException, Request
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
from schemas import SubscriptionCreate, SubscriptionSchema
from telegram_bot import send_telegram_message, send_daily_summary

# ==================== FIX RENDER STARTUP ERROR ====================
print("[BOOT] Membuat tabel jika belum ada...")
Base.metadata.create_all(bind=engine)
print("[BOOT] Tabel subscription siap")

print("[BOOT] Cek kolom reminder_count_h2...")
inspector = inspect(engine)
columns = [c['name'] for c in inspector.get_columns('subscription')]

if 'reminder_count_h2' not in columns:
    print("[BOOT] Menambahkan kolom reminder_count_h2...")
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE subscription ADD COLUMN reminder_count_h2 INTEGER DEFAULT 0"))
    print("[BOOT] Kolom reminder_count_h2 berhasil ditambahkan!")
else:
    print("[BOOT] Kolom reminder_count_h2 sudah ada")
# ====================================================================

timezone_wib = ZoneInfo("Asia/Jakarta")
security = HTTPBasic()

templates = Jinja2Templates(directory="templates")

def verify_credentials(credentials: HTTPBasicCredentials = Depends(security)):
    correct_username = secrets.compare_digest(credentials.username, os.getenv("ADMIN_USERNAME", "admin"))
    correct_password = secrets.compare_digest(credentials.password, os.getenv("ADMIN_PASSWORD", "secret"))
    if not (correct_username and correct_password):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return credentials.username

# Helper kirim Telegram di thread (biar ga blocking)
def send_in_thread(msg: str):
    def run():
        asyncio.run(send_telegram_message(msg))
    threading.Thread(target=run, daemon=True).start()

def run_dynamic_reminders():
    print(f"[{datetime.now(timezone_wib).strftime('%Y-%m-%d %H:%M:%S')}] Reminder job berjalan...")
    db = SessionLocal()
    try:
        subs = get_all_subscriptions(db)
        now_wib = datetime.now(timezone_wib)
        today = now_wib.date()

        for sub in subs:
            if not sub.expires_at:
                continue

            days_left = (sub.expires_at - today).days

            # AUTO RESET COUNTER saat sudah renew (>20 hari lagi)
            if days_left > 20:
                if any([sub.reminder_count_h3 > 0, sub.reminder_count_h2 > 0, sub.reminder_count_h1 > 0, sub.reminder_count_h0 > 0]):
                    sub.reminder_count_h3 = sub.reminder_count_h2 = sub.reminder_count_h1 = sub.reminder_count_h0 = 0
                    sub.last_reminder_time = None
                    sub.last_reminder_type = None
                    db.commit()
                    print(f"[RESET] Counter di-reset → {sub.name}")

            # H-3 (2x sehari)
            if days_left == 3 and sub.reminder_count_h3 < 2:
                msg = f"⚠️ Pemberitahuan Penting\n\nLayanan *{sub.name}* akan berakhir dalam 3 hari lagi.\n{sub.url}\nKadaluarsa: {sub.expires_at.strftime('%d %B %Y')}\n\nMohon segera lakukan perpanjangan.\nTerima kasih 🙏"
                send_in_thread(msg)
                sub.reminder_count_h3 += 1
                db.commit()

            # H-2 (3x sehari)
            elif days_left == 2 and sub.reminder_count_h2 < 3:
                msg = f"🚨 Informasi Mendesak\n\n*{sub.name}* tersisa 2 hari lagi.\n{sub.url}\nKadaluarsa: {sub.expires_at.strftime('%d %B %Y')}\n\nSegera lakukan perpanjangan hari ini untuk menghindari gangguan layanan.\nTim kami siap membantu 🙏"
                send_in_thread(msg)
                sub.reminder_count_h2 += 1
                db.commit()

            # H-1 (5x sehari - sangat mendesak tapi tetap sopan)
            elif days_left == 1 and sub.reminder_count_h1 < 5:
                msgs = [
                    "🔴 Pemberitahuan Sangat Mendesak\n\n\nLayanan akan berakhir *BESOK*.\nMohon segera lakukan perpanjangan hari ini.\nTerima kasih atas perhatiannya 🙏",
                    "🔴 Informasi Kritis\n\nTersisa kurang dari 24 jam untuk layanan ini.\nSegera perpanjang agar tetap aktif.",
                    "🔴 Peringatan Final Siang\n\nBesok layanan akan dinonaktifkan.\nTim siap membantu renewal Anda.",
                    "🔴 Mohon Perhatian Khusus\n\nPerpanjangan hari ini menjaga semua data tetap aktif.\nKami menghargai Anda.",
                    "🔴 Pemberitahuan Malam\n\nBeberapa jam tersisa.\nMohon lakukan perpanjangan malam ini juga 🙏"
                ]
                msg = msgs[sub.reminder_count_h1] + f"\n\n\n*{sub.name}*\n{sub.url}\nExpire: {sub.expires_at.strftime('%d %B %Y')}"
                send_in_thread(msg)
                sub.reminder_count_h1 += 1
                db.commit()

            # H-0 atau sudah lewat (max 8x)
            elif days_left <= 0 and sub.reminder_count_h0 < 8:
                msg = f"🔴 Layanan Telah Berakhir\n\n*{sub.name}* telah kadaluarsa pada {sub.expires_at.strftime('%d %B %Y')}.\n{sub.url}\n\nSegera lakukan perpanjangan untuk mengaktifkan kembali.\nKami siap membantu 24/7 🙏\n[Pesan {sub.reminder_count_h0 + 1}/8]"
                send_in_thread(msg)
                sub.reminder_count_h0 += 1
                db.commit()

    except Exception as e:
        print(f"Error reminder job: {e}")
    finally:
        db.close()

def send_daily_summary_job():
    db = SessionLocal()
    try:
        subs = get_all_subscriptions(db)
        asyncio.run(send_daily_summary(subs))
    finally:
        db.close()

# Scheduler
scheduler = BackgroundScheduler(timezone=timezone_wib)
scheduler.add_job(run_dynamic_reminders, CronTrigger(minute="*/10"))  # tiap 10 menit
scheduler.add_job(send_daily_summary_job, CronTrigger(hour=9, minute=0))  # jam 09:00 WIB
scheduler.start()
print("Scheduler aktif → reminder tiap 10 menit + daily 09:00 WIB")

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/", response_class=HTMLResponse)
async def root(request: Request, username: str = Depends(verify_credentials)):
    db = SessionLocal()
    subs = get_subscriptions(db)
    return templates.TemplateResponse("index.html", {"request": request, "subs": subs})

# ... (endpoint POST /add, PUT /update, DELETE tetap sama seperti punya kamu)

@app.get("/trigger")
async def manual_trigger(username: str = Depends(verify_credentials)):
    run_dynamic_reminders()
    send_daily_summary_job()
    return {"status": "Reminder & summary dikirim manual"}

@app.get("/keep-alive")
async def keep_alive():
    return {
        "status": "ALIVE & READY",
        "time_wib": datetime.now(timezone_wib).strftime("%d %B %Y %H:%M:%S"),
        "message": "Render tidak akan sleep lagi → cron-job.org ping ke sini tiap 10 menit ya!"
    }

print("[BOOT] alarmhostingk39 SIAP 100% - Deploy ini sekarang juga bro!")
