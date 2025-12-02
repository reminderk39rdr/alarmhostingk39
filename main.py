# main.py — K39 REMINDER HIDUP SELAMANYA — 3 DESEMBER 2025 💪🔥
import os
import threading
import secrets
import logging
from datetime import datetime, date
from zoneinfo import ZoneInfo
import re

from fastapi import FastAPI, Depends, HTTPException, Request, Form, status
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
from schemas import SubscriptionCreate
from models import Subscription
from crud import get_subscriptions, get_all_subscriptions, create_subscription, update_subscription, delete_subscription
from telegram_bot import send_telegram_message, send_daily_summary

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# =============================================
# DATABASE AUTO MIGRATION KOLOM (reminder_count + created_at)
# =============================================
Base.metadata.create_all(bind=engine)

logger.info("[BOOT] Auto add kolom kalau belum ada...")
try:
    with engine.begin() as conn:
        inspector = inspect(engine)
        columns = [col['name'] for col in inspector.get_columns('subscription')]
        for col in ['reminder_count_h3', 'reminder_count_h2', 'reminder_count_h1', 'reminder_count_h0', 'created_at']:
            if col not in columns:
                if col == 'created_at':
                    conn.execute(text("ALTER TABLE subscription ADD COLUMN created_at TIMESTAMP DEFAULT NOW()"))
                else:
                    conn.execute(text(f"ALTER TABLE subscription ADD COLUMN {col} INTEGER DEFAULT 0"))
                logger.info(f"[BOOT] Kolom {col} berhasil ditambahkan")
except Exception as e:
    logger.error(f"[BOOT] Gagal migrasi kolom: {e}")

logger.info("[BOOT] Database 100% siap — semua data lama aman!")

# =============================================
# KONFIG
# =============================================
timezone_wib = ZoneInfo("Asia/Jakarta")
security = HTTPBasic()
templates = Jinja2Templates(directory="templates")  # pastikan folder templates ada!

def verify_credentials(credentials: HTTPBasicCredentials = Depends(security)):
    correct_username = secrets.compare_digest(credentials.username, os.getenv("ADMIN_USERNAME", "adminrdr"))
    correct_password = secrets.compare_digest(credentials.password, os.getenv("ADMIN_PASSWORD", "j3las_kuat_39!"))
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Username/password salah bro",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

# =============================================
# VALIDATION (tanggal tidak boleh sudah lewat)
# =============================================
def validate_input(name: str, url: str, expires_at: str, brand: str | None = None):
    name = name.strip()
    url = url.strip()
    expires_at = expires_at.strip()
    brand = brand.strip() if brand else None

    if len(name) < 2:
        raise HTTPException(status_code=400, detail="Nama minimal 2 karakter")
    if not url.lower().startswith(('http://', 'https://')):
        raise HTTPException(status_code=400, detail="URL harus diawali http:// atau https://")
    if not re.match(r"^\d{2}/\d{2}/\d{4}$", expires_at):
        raise HTTPException(status_code=400, detail="Format tanggal harus mm/dd/yyyy")

    try:
        exp_date = datetime.strptime(expires_at, "%m/%d/%Y").date()
        if exp_date < date.today():
            raise HTTPException(status_code=400, detail="Tanggal expire tidak boleh sudah lewat!")
    except ValueError:
        raise HTTPException(status_code=400, detail="Tanggal tidak valid")

    return name, url, exp_date, brand

# =============================================
# TELEGRAM HELPER
# =============================================
async def safe_send(msg: str):
    try:
        await send_telegram_message(msg)
    except Exception as e:
        logger.error(f"Telegram gagal kirim: {e}")

def send_in_thread(msg: str):
    threading.Thread(target=lambda: asyncio.run(safe_send(msg)), daemon=True).start()

# =============================================
# REMINDER ENGINE — VERSI PALING GANAS + RESET COUNTER OTOMATIS
# =============================================
def run_dynamic_reminders():
    db = SessionLocal()
    try:
        today = datetime.now(timezone_wib).date()
        for sub in get_all_subscriptions(db):
            days_left = (sub.expires_at - today).days

            # Reset semua counter kalau sudah diperpanjang (>20 hari)
            if days_left > 20:
                reset = False
                for h in ['h3', 'h2', 'h1', 'h0']:
                    if getattr(sub, f'reminder_count_{h}', 0) > 0:
                        reset = True
                        setattr(sub, f'reminder_count_{h}', 0)
                if reset:
                    db.commit()

            expire_str = sub.expires_at.strftime('%d %B %Y')

            if days_left == 3 and getattr(sub, 'reminder_count_h3', 0) < 2:
                send_in_thread(f"⚠️ PERINGATAN DINI\n\n*{sub.name}* tinggal 3 hari lagi!\nLink: {sub.url}\nExpire: {expire_str}\n\nSegera perpanjang bro!")
                sub.reminder_count_h3 += 1
                db.commit()

            elif days_left == 2 and getattr(sub, 'reminder_count_h2', 0) < 3:
                send_in_thread(f"🚨 MENDESAK BANGET!\n\n*{sub.name}* tinggal 2 hari!\nLink: {sub.url}\nExpire: {expire_str}\n\nHari ini atau besok WAJIB renew!")
                sub.reminder_count_h2 += 1
                db.commit()

            elif days_left == 1 and getattr(sub, 'reminder_count_h1', 0) < 5:
                msgs = [
                    f"🔥 BESOK MATI TOTAL!\n\n*{sub.name}* tinggal <24 jam!\nLink: {sub.url}\nExpire: {expire_str}\n\nRENEW SEKARANG ATAU DATA ILANG SELAMANYA!",
                    f"🔥 H-1 BRO!!!\n\n*{sub.name}* besok langsung nonaktif!\n{sub.url}\n\nPerpanjang sekarang juga!",
                    f"🔥 FINAL WARNING!\n\n*{sub.name}* tinggal beberapa jam lagi!\n{sub.url}\n\nJANGAN SAMPAI MENYESAL NANTI!",
                    f"🔥 PERPANJANG HARI INI = DATA AMAN SELAMANYA\n\n*{sub.name}*\n{sub.url}",
                    f"🔥 MALAM TERAKHIR!\n\nKalau ga renew sekarang, besok mati permanen!\n{sub.url}",
                ]
                send_in_thread(msgs[getattr(sub, 'reminder_count_h1', 0)])
                sub.reminder_count_h1 += 1
                db.commit()

            elif days_left <= 0 and getattr(sub, 'reminder_count_h0', 0) < 8:
                days_exp = "hari ini" if days_left == 0 else f"{abs(days_left)} hari yang lalu"
                send_in_thread(f"💀 SUDAH EXPIRE {days_exp.upper()}!\n\n*{sub.name}* sudah kadaluarsa!\nLink: {sub.url}\nExpire: {expire_str}\n\nRENEW SEKARANG sebelum dihapus provider!")
                sub.reminder_count_h0 += 1
                db.commit()
    except Exception as e:
        logger.error(f"Reminder engine error: {e}")
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
# SCHEDULER — REMINDER TIAP 7 MENIT (super responsif)
# =============================================
scheduler = BackgroundScheduler(timezone=timezone_wib)
scheduler.add_job(run_dynamic_reminders, "interval", minutes=7, next_run_time=datetime.now(timezone_wib))
scheduler.add_job(daily_job, CronTrigger(hour=8, minute=30))  # setiap hari jam 08:30 WIB
scheduler.start()

# =============================================
# FASTAPI APP
# =============================================
app = FastAPI(title="K39 Reminder — HIDUP SELAMANYA 🔥")

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/", response_class=HTMLResponse)
async def root(request: Request, username: str = Depends(verify_credentials)):
    db = SessionLocal()
    subs = []
    error_msg = None
    try:
        subs = get_subscriptions(db)
    except Exception as e:
        error_msg = f"Database error: {str(e)}"
        logger.error(f"[ROOT] Load subscriptions error: {e}")
    finally:
        db.close()

    return templates.TemplateResponse("index.html", {
        "request": request,
        "subs": subs,
        "today": datetime.now(timezone_wib).date(),
        "now": datetime.now(timezone_wib),
        "error_msg": error_msg
    })

@app.post("/add")
async def add(username: str = Depends(verify_credentials), name: str = Form(...), url: str = Form(...), brand: str | None = Form(None), expires_at: str = Form(...)):
    name, url, exp_date, brand = validate_input(name, url, expires_at, brand)
    db = SessionLocal()
    try:
        create_subscription(db, SubscriptionCreate(name=name, url=url, expires_at=exp_date, brand=brand))
    finally:
        db.close()
    return RedirectResponse(url="/", status_code=303)

@app.post("/update/{sub_id}")
async def update(sub_id: int, username: str = Depends(verify_credentials), name: str = Form(...), url: str = Form(...), brand: str | None = Form(None), expires_at: str = Form(...)):
    name, url, exp_date, brand = validate_input(name, url, expires_at, brand)
    db = SessionLocal()
    try:
        update_subscription(db, sub_id, SubscriptionCreate(name=name, url=url, expires_at=exp_date, brand=brand))
    finally:
        db.close()
    return RedirectResponse(url="/", status_code=303)

@app.post("/delete/{sub_id}")
async def delete(sub_id: int, username: str = Depends(verify_credentials)):
    db = SessionLocal()
    try:
        delete_subscription(db, sub_id)
    finally:
        db.close()
    return RedirectResponse(url="/", status_code=303)

@app.get("/trigger")
async def trigger(username: str = Depends(verify_credentials)):
    run_dynamic_reminders()
    daily_job()
    return {"status": "Reminder + daily summary langsung dijalankan!"}

@app.get("/db-test")
async def db_test():
    try:
        db = SessionLocal()
        count = db.query(Subscription).count()
        db.close()
        return {"status": "PostgreSQL Connected", "subscriptions_count": count, "time": datetime.now(timezone_wib).isoformat()}
    except Exception as e:
        return {"error": str(e)}

@app.get("/keep-alive")
async def keep_alive():
    return {
        "status": "HIDUP BRO 100%!!!",
        "time": datetime.now(timezone_wib).strftime("%d %B %Y %H:%M:%S WIB"),
        "message": "K39 ga akan pernah mati lagi 🔥"
    }

logger.info("K39 Reminder — BOOT 100% SUKSES — HIDUP SELAMANYA! 🚀🔥💪")
