# main.py
import os
import threading
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
from fastapi import FastAPI, Depends, HTTPException
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from sqlalchemy import text, inspect
from contextlib import asynccontextmanager
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import asyncio

from database import engine, SessionLocal, Base
from models import Subscription
from schemas import SubscriptionCreate, Subscription as SubscriptionSchema
from crud import (
    get_subscriptions,
    create_subscription,
    delete_subscription,
    update_subscription,
    get_all_subscriptions,
)
from telegram_bot import send_telegram_message, send_daily_summary

# --- Zona waktu WIB ---
timezone_wib = ZoneInfo("Asia/Jakarta")

# Buat tabel + tambah column kalau belum ada
Base.metadata.create_all(bind=engine)

# Tambah column reminder_count_h2 kalau belum ada (aman untuk SQLite/Postgres)
inspector = inspect(engine)
if 'reminder_count_h2' not in [c['name'] for c in inspector.get_columns('subscription')]:
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE subscription ADD COLUMN reminder_count_h2 INTEGER DEFAULT 0"))
    print("Column reminder_count_h2 berhasil ditambahkan")

# HTTP Basic Auth
security = HTTPBasic()

def verify_credentials(credentials: HTTPBasicCredentials = Depends(security)):
    correct_user = secrets.compare_digest(credentials.username, os.getenv("ADMIN_USERNAME", "admin"))
    correct_pass = secrets.compare_digest(credentials.password, os.getenv("ADMIN_PASSWORD", "secret"))
    if not (correct_user and correct_pass):
        raise HTTPException(status_code=401, detail="Unauthorized", headers={"WWW-Authenticate": "Basic"})
    return credentials.username

# Helper biar code bersih
def send_in_thread(msg: str):
    def run():
        asyncio.run(send_telegram_message(msg))
    threading.Thread(target=run).start()

def run_dynamic_reminders():
    print("[Scheduler] Dynamic reminders job started")
    db = SessionLocal()
    try:
        subscriptions = get_all_subscriptions(db)
        now_wib = datetime.now(timezone_wib)
        today_wib = now_wib.date()

        for sub in subscriptions:
            if not sub.expires_at:
                continue

            days_left = (sub.expires_at - today_wib).days

            # AUTO RESET COUNTER saat sudah jauh dari expire (>20 hari)
            if days_left > 20:
                if any([sub.reminder_count_h3, sub.reminder_count_h2, sub.reminder_count_h1, sub.reminder_count_h0]):
                    sub.reminder_count_h3 = sub.reminder_count_h2 = sub.reminder_count_h1 = sub.reminder_count_h0 = 0
                    sub.last_reminder_time = None
                    sub.last_reminder_type = None
                    db.commit()
                    print(f"[RESET] Counters di-reset untuk {sub.name} (days_left={days_left})")

            # H-3 Reminder (2x)
            if days_left == 3 and sub.reminder_count_h3 < 2:
                msg = f"⚠️ Pemberitahuan Penting\n\nLayanan '{sub.name}' akan berakhir dalam 3 hari lagi.\n{sub.url}\nTanggal kadaluarsa: {sub.expires_at.strftime('%d %B %Y')}\n\nMohon segera lakukan perpanjangan untuk menjaga kelancaran layanan Anda.\n\nTerima kasih atas perhatiannya. 🙏"
                if sub.reminder_count_h3 == 1:
                    msg = msg.replace("Pemberitahuan Penting", "Pemberitahuan Kedua")
                send_in_thread(msg)
                sub.reminder_count_h3 += 1
                db.commit()

            # H-2 Reminder (3x)
            elif days_left == 2 and sub.reminder_count_h2 < 3:
                msg = f"🚨 Informasi Mendesak\n\nLayanan '{sub.name}' akan berakhir dalam 2 hari.\n{sub.url}\nKadaluarsa: {sub.expires_at.strftime('%d %B %Y')}\n\nUntuk menghindari gangguan, mohon segera lakukan perpanjangan hari ini.\n\nTim kami siap membantu. 🙏"
                if sub.reminder_count_h2 > 0:
                    msg = msg.replace("Informasi Mendesak", f"Pengingat ke-{sub.reminder_count_h2 + 1}")
                send_in_thread(msg)
                sub.reminder_count_h2 += 1
                db.commit()

            # H-1 Reminder (5x)
            elif days_left == 1 and sub.reminder_count_h1 < 5:
                msgs = [
                    "🔴 Pemberitahuan Sangat Mendesak\n\nLayanan akan berakhir BESOK.\nMohon segera lakukan perpanjangan hari ini untuk menghindari penghentian layanan.\nTerima kasih. 🙏",
                    "🔴 Informasi Kritis\n\nTersisa < 24 jam untuk layanan ini.\nSegera lakukan perpanjangan agar tetap aktif tanpa interupsi.",
                    "🔴 Peringatan Final Siang Ini\n\nBesok layanan akan nonaktif.\nTim kami siap membantu proses renewal Anda.",
                    "🔴 Mohon Perhatian Khusus\n\nPerpanjangan hari ini akan menjaga semua data tetap aktif.\nKami sangat menghargai Anda.",
                    "🔴 Pemberitahuan Malam Ini\n\nHanya beberapa jam tersisa.\nMohon lakukan perpanjangan malam ini juga. 🙏"
                ]
                msg = f"{msgs[sub.reminder_count_h1]}\n\n{sub.name}\n{sub.url}\nExpire: {sub.expires_at.strftime('%d %B %Y')}"
                send_in_thread(msg)
                sub.reminder_count_h1 += 1
                db.commit()

            # H-0 atau sudah lewat (max 8x)
            elif days_left <= 0 and sub.reminder_count_h0 < 8:
                msg = f"🔴 Layanan Telah Berakhir\n\n'{sub.name}' telah kadaluarsa pada {sub.expires_at.strftime('%d %B %Y')}.\n{sub.url}\n\nMohon segera lakukan perpanjangan untuk mengaktifkan kembali.\nTim kami siap membantu 24/7. 🙏\n[Pesan {sub.reminder_count_h0 + 1}/8]"
                send_in_thread(msg)
                sub.reminder_count_h0 += 1
                db.commit()

    except Exception as e:
        print(f"Error di reminder: {e}")
    finally:
        db.close()

def send_daily_summary_job():
    db = SessionLocal()
    try:
        subs = get_all_subscriptions(db)
        asyncio.run(send_daily_summary(subs))
    finally:
        db.close()

@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = BackgroundScheduler()
    scheduler.add_job(run_dynamic_reminders, CronTrigger(minute="*/10", timezone=timezone_wib))
    scheduler.add_job(send_daily_summary_job, CronTrigger(hour=9, minute=0, timezone=timezone_wib), id='daily_summary')
    scheduler.start()
    print("Schedulers aktif (reminder tiap 10 menit + daily 09:00 WIB)")
    yield
    scheduler.shutdown()

app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"))

# ... (semua endpoint lainnya tetap sama seperti versi lu sekarang)

@app.get("/trigger")
async def trigger(username: str = Depends(verify_credentials)):
    run_dynamic_reminders()
    send_daily_summary_job()
    return {"status": "Triggered"}