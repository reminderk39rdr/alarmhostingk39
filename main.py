# main.py
import os
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
from datetime import date, timedelta, datetime

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

# Fungsi untuk reminder dinamis (H-3, H-1, H-0)
def run_dynamic_reminders():
    """
    Fungsi utama untuk mengecek semua subscription dan mengatur reminder dinamis.
    """
    db = SessionLocal()
    try:
        subscriptions = get_all_subscriptions(db)
        now = datetime.now()
        today = date.today()

        for sub in subscriptions:
            expires_at = sub.expires_at

            # --- Cek H-3 Reminder ---
            if expires_at == today + timedelta(days=3):
                if sub.reminder_count_h3 < 2: # Belum kirim 2 kali
                    if sub.reminder_count_h3 == 0:
                        # Kirim reminder pertama H-3
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
                        sub.last_reminder_time = now
                        sub.last_reminder_type = 'h3'
                        db.commit()
                    elif sub.reminder_count_h3 == 1:
                        # Cek apakah sudah waktunya kirim reminder kedua (misalnya, 12 jam setelah yang pertama)
                        if now - sub.last_reminder_time >= timedelta(hours=12):
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
                            sub.last_reminder_time = now
                            sub.last_reminder_type = 'h3'
                            db.commit()

            # --- Cek H-1 Reminder ---
            elif expires_at == today + timedelta(days=1):
                if sub.reminder_count_h1 < 3: # Belum kirim 3 kali
                    if sub.reminder_count_h1 == 0:
                        # Kirim reminder pertama H-1
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
                        sub.last_reminder_time = now
                        sub.last_reminder_type = 'h1'
                        db.commit()
                    elif sub.reminder_count_h1 == 1:
                        # Kirim reminder kedua H-1 (misalnya, 4 jam setelah yang pertama)
                        if now - sub.last_reminder_time >= timedelta(hours=4):
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
                            sub.last_reminder_time = now
                            sub.last_reminder_type = 'h1'
                            db.commit()
                    elif sub.reminder_count_h1 == 2:
                        # Kirim reminder ketiga H-1 (misalnya, 2 jam setelah yang kedua)
                        if now - sub.last_reminder_time >= timedelta(hours=2):
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
                            sub.last_reminder_time = now
                            sub.last_reminder_type = 'h1'
                            db.commit()

            # --- Cek Hari H Reminder ---
            elif expires_at == today:
                # Jika expired hari ini dan belum dihapus/diperpanjang
                # Kirim reminder setiap 5 menit
                if now - sub.last_reminder_time >= timedelta(minutes=5) if sub.last_reminder_time else True:
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
                     sub.last_reminder_time = now
                     sub.last_reminder_type = 'h0'
                     db.commit()

    except Exception as e:
        print(f"🚨 Error saat run_dynamic_reminders: {e}")
    finally:
        db.close()

# Fungsi untuk daily summary
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
    # Scheduler utama: cek setiap 10 menit untuk reminder dinamis
    scheduler.add_job(run_dynamic_reminders, IntervalTrigger(minutes=10), id='dynamic_reminders')
    # Scheduler baru: kirim summary setiap hari jam 9 pagi
    scheduler.add_job(send_daily_summary_job, CronTrigger(hour=9, minute=0), id='daily_summary')
    scheduler.start()
    print("✅ Dynamic Reminder Scheduler started (every 10 minutes)")
    print("✅ Daily Summary Scheduler started (daily at 9:00 AM)")
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
