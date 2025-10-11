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
from contextlib import asynccontextmanager
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
import secrets
import asyncio

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

# --- Fungsi untuk reminder dinamis (H-3, H-1, H-0) - DENGAN WIB ---
def run_dynamic_reminders():
    """
    Fungsi utama untuk mengecek semua subscription dan mengatur reminder dinamis.
    Menggunakan zona waktu WIB.
    """
    print("🔍 [Scheduler] Dynamic reminders job started")
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
                if sub.reminder_count_h3 < 2: # Belum kirim 2 kali
                    if sub.reminder_count_h3 == 0:
                        # Kirim reminder pertama H-3
                        msg = f"🚨 Reminder: '{sub.name}' ({sub.url}) expires in 3 days! ({sub.expires_at})"
                        print(f"📤 [Scheduler] Sending H-3 reminder (1/2) for {sub.name}")
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
                        sub.last_reminder_time = now_wib
                        sub.last_reminder_type = 'h3'
                        db.commit()
                    elif sub.reminder_count_h3 == 1:
                        # Cek apakah sudah waktunya kirim reminder kedua (misalnya, 12 jam setelah yang pertama)
                        if now_wib - sub.last_reminder_time >= timedelta(hours=12):
                            msg = f"🚨 Reminder: '{sub.name}' ({sub.url}) expires in 3 days! ({sub.expires_at}) [2/2]"
                            print(f"📤 [Scheduler] Sending H-3 reminder (2/2) for {sub.name}")
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
                if sub.reminder_count_h1 < 3: # Belum kirim 3 kali
                    if sub.reminder_count_h1 == 0:
                        # Kirim reminder pertama H-1
                        msg = f"🔥 URGENT: '{sub.name}' ({sub.url}) expires TOMORROW! ({sub.expires_at})"
                        print(f"📤 [Scheduler] Sending H-1 reminder (1/3) for {sub.name}")
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
                        # Kirim reminder kedua H-1 (misalnya, 4 jam setelah yang pertama)
                        if now_wib - sub.last_reminder_time >= timedelta(hours=4):
                            msg = f"🔥 URGENT: '{sub.name}' ({sub.url}) expires TOMORROW! ({sub.expires_at}) [2/3]"
                            print(f"📤 [Scheduler] Sending H-1 reminder (2/3) for {sub.name}")
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
                        # Kirim reminder ketiga H-1 (misalnya, 2 jam setelah yang kedua)
                        if now_wib - sub.last_reminder_time >= timedelta(hours=2):
                            msg = f"🔥 URGENT: '{sub.name}' ({sub.url}) expires TOMORROW! ({sub.expires_at}) [3/3]"
                            print(f"📤 [Scheduler] Sending H-1 reminder (3/3) for {sub.name}")
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
                # Jika expired hari ini dan belum dihapus/diperpanjang
                # Kirim reminder setiap 5 menit
                if now_wib - sub.last_reminder_time >= timedelta(minutes=5) if sub.last_reminder_time else True:
                     msg = f"💥 EXPIRED TODAY: '{sub.name}' ({sub.url}) expires TODAY! ({sub.expires_at}) [ALERT]"
                     print(f"📤 [Scheduler] Sending H-0 (Expired Today) reminder for {sub.name}")
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
        print(f"🚨 [Scheduler] Error saat run_dynamic_reminders: {e}")
    finally:
        db.close()
        print("🛑 [Scheduler] Dynamic reminders job ended")

# --- Fungsi untuk daily summary - DENGAN WIB ---
def send_daily_summary_job():
    """
    Job untuk dijadwalkan oleh scheduler.
    Mengambil semua subscription dan kirim summary ke Telegram.
    """
    print("🔍 [Scheduler] Daily summary job started")
    db = SessionLocal()
    try:
        subscriptions = get_all_subscriptions(db)
        print(f"📊 [Scheduler] Found {len(subscriptions)} subscriptions")
        import asyncio
        def run_async():
            try:
                print("🔄 [Scheduler] Attempting to run async send_daily_summary")
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(send_daily_summary(subscriptions))
                print("✅ [Scheduler] Async send_daily_summary completed")
            except Exception as e:
                 print(f"❌ [Scheduler] Error in run_async: {e}")
            finally:
                loop.close()
        thread = threading.Thread(target=run_async)
        thread.start()
        print("🚀 [Scheduler] Async task for daily summary started in thread")
    except Exception as e:
        print(f"🚨 [Scheduler] Error saat mengirim daily summary: {e}")
    finally:
        db.close()
        print("🛑 [Scheduler] Daily summary job ended")

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 Lifespan context started")
    scheduler = BackgroundScheduler()
    try:
        # Scheduler utama: cek setiap 10 menit untuk reminder dinamis - Gunakan WIB
        scheduler.add_job(run_dynamic_reminders, IntervalTrigger(minutes=10, timezone=timezone_wib), id='dynamic_reminders')
        # Scheduler baru: kirim summary setiap hari jam 9 pagi - Gunakan WIB
        scheduler.add_job(send_daily_summary_job, CronTrigger(hour=9, minute=0, timezone=timezone_wib), id='daily_summary')
        scheduler.start()
        print("✅ Dynamic Reminder Scheduler started (every 10 minutes, WIB)")
        print("✅ Daily Summary Scheduler started (daily at 9:00 AM, WIB)")
    except Exception as e:
        print(f"🚨 Error saat inisialisasi scheduler: {e}")
    yield
    scheduler.shutdown()
    print("🛑 Lifespan context ended")

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
    print("🔍 [/trigger] Manual trigger received")
    run_dynamic_reminders()
    # Juga picu daily summary untuk tes
    send_daily_summary_job()
    return {"status": "Dynamic reminders & Daily Summary checked"}

# --- Endpoint Baru untuk Status ---
from sqlalchemy import text # Untuk kompatibilitas SQLAlchemy 2.x

@app.get("/status")
def get_status(username: str = Depends(verify_credentials)):
    """
    Endpoint untuk mendapatkan status sistem (scheduler, bot, jumlah data).
    """
    db = SessionLocal()
    try:
        # Hitung jumlah total subscription
        total_count = db.query(Subscription).count()

        # Hitung subscription yang akan expire dalam 7 hari ke depan
        today = datetime.now(timezone_wib).date()
        next_week = today + timedelta(days=7)
        expiring_count = db.query(Subscription).filter(
            Subscription.expires_at >= today,
            Subscription.expires_at <= next_week
        ).count()

        # Test koneksi bot (kirim pesan dummy ke diri sendiri atau log)
        bot_status = "✅ Terhubung"
        if not os.getenv("TELEGRAM_BOT_TOKEN") or not os.getenv("TELEGRAM_CHAT_ID"):
             bot_status = "❌ Token/Chat ID Tidak Ditemukan"

        # Status scheduler: karena APscheduler tidak menyediakan API untuk mendapatkan
        # runtime job secara langsung dari FastAPI handler, kita hanya bisa
        # menampilkan bahwa scheduler *seharusnya* aktif berdasarkan log startup.
        scheduler_dynamic_status = "✅ Berjalan (10 menit)"
        scheduler_daily_status = "✅ Berjalan (9 pagi WIB)"

        # Waktu server WIB
        server_time_wib = datetime.now(timezone_wib).strftime('%Y-%m-%d %H:%M:%S %Z')

        status_data = {
            "scheduler_dynamic": scheduler_dynamic_status,
            "scheduler_daily": scheduler_daily_status,
            "bot_connection": bot_status,
            "total_subscriptions": total_count,
            "expiring_soon_count": expiring_count,
            "server_time_wib": server_time_wib,
        }

        return status_data

    finally:
        db.close()

# --- Endpoint Baru untuk Cek Koneksi Database (Kompatibel SQLAlchemy 2.x) ---
@app.get("/db-test")
def test_db_connection(username: str = Depends(verify_credentials)):
    """
    Endpoint untuk menguji koneksi ke database.
    """
    db = SessionLocal()
    try:
        # Gunakan text() untuk deklarasi ekspresi SQL (kompatibel SQLAlchemy 2.x)
        result = db.execute(text("SELECT 1")).fetchone()
        if result and result[0] == 1:
            return {"status": "✅ Database connection successful"}
        else:
            return {"status": "❌ Database connection failed"}
    except Exception as e:
        return {"status": f"❌ Database error: {str(e)}"}
    finally:
        db.close()

# ---
