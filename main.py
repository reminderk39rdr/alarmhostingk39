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
                        # Perbaiki f-string: gunakan kutip ganda di luar, atau escape kutip dalam
                        # Asli: f"🚨 Reminder: '{sub.name}' ({sub.url}) expires in 3 days! ({sub.expires_at})"
                        # Ini seharusnya valid, tapi mari kita jaga agar tidak ada kesalahan encoding atau parsing
                        # Kita tetap gunakan kutip tunggal dalam f-string, tapi pastikan penulisan benar
                        # Baris bermasalah di log adalah: msg = f"🚨 Reminder: '{sub
                        # Artinya, parser Python berhenti di '{sub dan mengira '{' tidak ditutup.
                        # Ini bisa terjadi jika ada karakter tak terlihat atau kutip tidak seimbang sebelumnya.
                        # Kita coba gunakan kutip ganda di luar untuk menghindari kebingungan parser.
                        # msg = f"🚨 Reminder: '{sub.name}' ({sub.url}) expires in 3 days! ({sub.expires_at})"
                        # Atau, kita gunakan escape untuk kutip tunggal di dalam string jika diperlukan.
                        # msg = f"🚨 Reminder: \'{sub.name}\' ({sub.url}) expires in 3 days! ({sub.expires_at})"
                        # Atau, kita gunakan format string biasa untuk menghindari masalah parsing.
                        # msg = "🚨 Reminder: '{}' ({}) expires in 3 days! ({})".format(sub.name, sub.url, sub.expires_at)
                        # Namun, f-string adalah standar. Kita pastikan tidak ada kutip yang tidak seimbang.
                        # Baris yang menyebabkan error adalah baris 74 (dalam log sebelumnya).
                        # Dalam versi sebelumnya, baris 74 mungkin mengandung kutip yang tidak seimbang.
                        # Kita coba tulis ulang baris ini dengan hati-hati.
                        msg = f"🚨 Reminder: '{sub.name}' ({sub.url}) expires in 3 days! ({sub.expires_at})"
                        import asyncio
                        def run_async():
                            try:
                                loop = asyncio.new_event_loop()
                                asyncio.set_event_loop(loop)
                                loop.run_until_complete(send_telegram_message(msg))
                            finally:
                                loop.close()
                        thread = threading.Thread(target=run_async)
                        thread.start()
                        sub.reminder_count_h3 = 1
                        # Simpan waktu WIB ke database
                        sub.last_reminder_time = now_wib
                        sub.last_reminder_type = 'h3'
                        db.commit()
                    elif sub.reminder_count_h3 == 1:
                        # Cek jeda waktu WIB
                        if now_wib - sub.last_reminder_time >= timedelta(hours=12):
                            msg = f"🚨 Reminder: '{sub.name}' ({sub.url}) expires in 3 days! ({sub.expires_at}) [2/2]"
                            import asyncio
                            def run_async():
                                try:
                                    loop = asyncio.new_event_loop()
                                    asyncio.set_event_loop(loop)
                                    loop.run_until_complete(send_telegram_message(msg))
                                finally:
                                    loop.close()
                            thread = threading.Thread(target=run_async)
                            thread.start()
                            sub.reminder_count_h3 = 2
                            sub.last_reminder_time = now_wib
                            sub.last_reminder_type = 'h3'
                            db.commit()

            # --- Cek H-1 Reminder ---
            elif expires_at == today_wib + timedelta(days=1):
                if sub.reminder_count_h1 < 3:
                    if sub.reminder_count_h1 == 0:
                        # Perbaiki f-string: gunakan kutip ganda di luar, atau escape kutip dalam
                        msg = f"🔥 URGENT: '{sub.name}' ({sub.url}) expires TOMORROW! ({sub.expires_at})"
                        import asyncio
                        def run_async():
                            try:
                                loop = asyncio.new_event_loop()
                                asyncio.set_event_loop(loop)
                                loop.run_until_complete(send_telegram_message(msg))
                            finally:
                                loop.close()
                        thread = threading.Thread(target=run_async)
                        thread.start()
                        sub.reminder_count_h1 = 1
                        sub.last_reminder_time = now_wib
                        sub.last_reminder_type = 'h1'
                        db.commit()
                    elif sub.reminder_count_h1 == 1:
                        if now_wib - sub.last_reminder_time >= timedelta(hours=4):
                            msg = f"🔥 URGENT: '{sub.name}' ({sub.url}) expires TOMORROW! ({sub.expires_at}) [2/3]"
                            import asyncio
                            def run_async():
                                try:
                                    loop = asyncio.new_event_loop()
                                    asyncio.set_event_loop(loop)
                                    loop.run_until_complete(send_telegram_message(msg))
                                finally:
                                    loop.close()
                            thread = threading.Thread(target=run_async)
                            thread.start()
                            sub.reminder_count_h1 = 2
                            sub.last_reminder_time = now_wib
                            sub.last_reminder_type = 'h1'
                            db.commit()
                    elif sub.reminder_count_h1 == 2:
                        if now_wib - sub.last_reminder_time >= timedelta(hours=2):
                            msg = f"🔥 URGENT: '{sub.name}' ({sub.url}) expires TOMORROW! ({sub.expires_at}) [3/3]"
                            import asyncio
                            def run_async():
                                try:
                                    loop = asyncio.new_event_loop()
                                    asyncio.set_event_loop(loop)
                                    loop.run_until_complete(send_telegram_message(msg))
                                finally:
                                    loop.close()
                            thread = threading.Thread(target=run_async)
                            thread.start()
                            sub.reminder_count_h1 = 3
                            sub.last_reminder_time = now_wib
                            sub.last_reminder_type = 'h1'
                            db.commit()

            # --- Cek Hari H Reminder ---
            elif expires_at == today_wib:
                if now_wib - sub.last_reminder_time >= timedelta(minutes=5) if sub.last_reminder_time else True:
                     # Perbaiki f-string: gunakan kutip ganda di luar, atau escape kutip dalam
                     msg = f"💥 EXPIRED TODAY: '{sub.name}' ({sub.url}) expires TODAY! ({sub.expires_at}) [ALERT]"
                     import asyncio
                     def run_async():
                         try:
                             loop = asyncio.new_event_loop()
                             asyncio.set_event_loop(loop)
                             loop.run_until_complete(send_telegram_message(msg))
                         finally:
                             loop.close()
                     thread = threading.Thread(target=run_async)
                     thread.start()
                     sub.reminder_count_h0 += 1
                     sub.last_reminder_time = now_wib
                     sub.last_reminder_type = 'h0'
                     db.commit()

    except Exception as e:
        print(f"🚨 Error saat run_dynamic_reminders: {e}")
    finally:
        db.close()

# Fungsi untuk daily summary - DENGAN WIB
def send_daily_summary_job():
    """
    Job untuk dijadwalkan oleh scheduler.
    Mengambil semua subscription dan kirim summary ke Telegram.
    """
    db = SessionLocal()
    try:
        subscriptions = get_all_subscriptions(db)
        import asyncio
        def run_async():
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(send_daily_summary(subscriptions))
            finally:
                loop.close()
        thread = threading.Thread(target=run_async)
        thread.start()
    except Exception as e:
        print(f"🚨 Error saat mengirim daily summary: {e}")
    finally:
        db.close()

@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = BackgroundScheduler()
    # Scheduler utama: cek setiap 10 menit untuk reminder dinamis - Gunakan WIB
    scheduler.add_job(run_dynamic_reminders, IntervalTrigger(minutes=10, timezone=timezone_wib), id='dynamic_reminders')
    # Scheduler baru: kirim summary setiap hari jam 9 pagi - Gunakan WIB
    scheduler.add_job(send_daily_summary_job, CronTrigger(hour=9, minute=0, timezone=timezone_wib), id='daily_summary')
    scheduler.start()
    print("✅ Dynamic Reminder Scheduler started (every 10 minutes, WIB)")
    print("✅ Daily Summary Scheduler started (daily at 9:00 AM, WIB)")
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
    run_dynamic_reminders()
    return {"status": "Dynamic reminders checked"}
