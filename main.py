# main.py — RDR Hosting Reminder — VERSI ABADI PREMIUM — 03 DESEMBER 2025
import os
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
import secrets
import re
from collections import defaultdict

from fastapi import FastAPI, Depends, HTTPException, Request, Form, Form, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from database import engine, SessionLocal, Base
from models import Subscription
from schemas import SubscriptionCreate
from crud import get_subscriptions, get_all_subscriptions, create_subscription, update_subscription, delete_subscription
from telegram_bot import send_full_list_trigger, send_daily_summary

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("RDR")

app = FastAPI(title="RDR Hosting Reminder", openapi_url="/openapi.json", docs_url="/docs")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

timezone_wib = ZoneInfo("Asia/Jakarta")
security = HTTPBasic()

# ===================================
# BOOT: DATABASE CONNECTION TEST + MIGRATION
# ===================================
logger.info("[BOOT] Menghubungkan ke PostgreSQL...")
try:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    logger.info("[BOOT] Database terkoneksi — semua data aman selamanya!")

    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        inspector = inspect(engine)
        columns = [col['name'] for col in inspector.get_columns('subscription')]
        required_cols = ['reminder_count_h3', 'reminder_count_h2', 'reminder_count_h1', 'reminder_count_h0', 'created_at']
        for col in required_cols:
            if col not in columns:
                if col == 'created_at':
                    conn.execute(text("ALTER TABLE subscription ADD COLUMN created_at TIMESTAMP DEFAULT NOW()"))
                else:
                    conn.execute(text(f"ALTER TABLE subscription ADD COLUMN {col} INTEGER DEFAULT 0"))
                logger.info(f"[BOOT] Kolom {col} ditambahkan")

except Exception as e:
    logger.critical(f"[BOOT] GAGAL TERHUBUNG DATABASE: {e}")
    raise RuntimeError("Database connection failed — check DATABASE_URL")

# ===================================
# AUTH
# ===================================
def verify_credentials(credentials: HTTPBasicCredentials = Depends(security)):
    correct_username = secrets.compare_digest(credentials.username, os.getenv("ADMIN_USERNAME", "adminrdr"))
    correct_password = secrets.compare_digest(credentials.password, os.getenv("ADMIN_PASSWORD", "j3las_kuat39!"))
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Username atau password salah",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

# ===================================
# VALIDATION
# ===================================
def validate_input(name: str, url: str, expires_at: str, brand: str | None = None):
    name = name.strip()
    url = url.strip()
    expires_at = expires_at.strip()
    brand = brand.strip() if brand else None

    if len(name) < 3:
        raise HTTPException(status_code=400, detail="Nama service minimal 3 karakter")
    if not url.lower().startswith(('http://', 'https://')):
        raise HTTPException(status_code=400, detail="URL harus diawali http:// atau https://")
    if not re.match(r"^\d{2}/\d{2}/\d{4}$", expires_at):
        raise HTTPException(status_code=400, detail="Format tanggal mm/dd/yyyy")

    try:
        exp_date = datetime.strptime(expires_at, "%m/%d/%Y").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Tanggal tidak valid")

    return name, url, exp_date, brand

# ===================================
# ROUTES — CLEAN & PROFESSIONAL
# ===================================
@app.get("/", response_class=HTMLResponse)
async def root(request: Request, username: str = Depends(verify_credentials)):
    db = SessionLocal()
    try:
        subs = get_subscriptions(db)

        grouped = defaultdict(list)
        for sub in subs:
            key = (sub.brand or "Tanpa Brand").strip().upper()
            grouped[key].append(sub)
        grouped = dict(sorted(grouped.items()))
    except Exception as e:
        logger.error(f"[ROOT] DB Error: {e}")
        subs = []
        grouped = {}
    finally:
        db.close()

    return templates.TemplateResponse("index.html", {
        "request": request,
        "subs": subs,
        "grouped": grouped,
        "today": datetime.now(timezone_wib).date(),
        "now": datetime.now(timezone_wib)
    })

@app.post("/add")
async def add(username: str = Depends(verify_credentials), name: str = Form(...), url: str = Form(...), brand: str | None = Form(None), expires_at: str = Form(...)):
    name, url, exp_date, brand = validate_input(name, url, expires_at, brand)
    db = SessionLocal()
    try:
        create_subscription(db, SubscriptionCreate(name=name, url=url, expires_at=exp_date, brand=brand))
        db.commit()
    except Exception as e:
        logger.error(f"[ADD] Error: {e}")
        raise HTTPException(status_code=500, detail="Gagal menambah subscription")
    finally:
        db.close()
    return RedirectResponse("/", status_code=303)

@app.post("/update/{sub_id}")
async def update(sub_id: int, username: str = Depends(verify_credentials), name: str = Form(...), url: str = Form(...), brand: str | None = Form(None), expires_at: str = Form(...)):
    name, url, exp_date, brand = validate_input(name, url, expires_at, brand)
    db = SessionLocal()
    try:
        result = update_subscription(db, sub_id, SubscriptionCreate(name=name, url=url, expires_at=exp_date, brand=brand))
        db.commit()
        if not result:
            raise HTTPException(status_code=404, detail="Subscription tidak ditemukan")
    finally:
        db.close()
    return RedirectResponse("/", status_code=303)

@app.post("/delete/{sub_id}")
async def delete(sub_id: int, username: str = Depends(verify_credentials)):
    db = SessionLocal()
    try:
        delete_subscription(db, sub_id)
        db.commit()
    finally:
        db.close()
    return RedirectResponse("/", status_code=303)

@app.get("/trigger")
async def trigger(username: str = Depends(verify_credentials)):
    await send_full_list_trigger()
    return HTMLResponse(
        "<div style='text-align:center;padding:120px;background:#0a0a0f;color:#8b5cf6;font-family:system-ui'><h2>List per brand telah dikirim ke Telegram</h2><p><a href='/' style='color:#fff;text-decoration:none;font-size:1.2rem'>← Kembali ke Dashboard</a></p></div>"
    )

@app.get("/keep-alive")
async def keep_alive():
    try:
        db = SessionLocal()
        count = db.query(Subscription).count()
        db.close()
    except:
        count = "error"
    return {
        "status": "RDR Hosting Reminder — HIDUP 100% ABADI",
        "time": datetime.now(timezone_wib).strftime("%d %B %Y %H:%M:%S WIB"),
        "total_subscription": count,
        "message": "Semua aman bro. Kamu sudah menang total."
    }

# ===================================
# REMINDER OTOMATIS PALING GANAS (H-3, H-2, H-1, Expired)
# ===================================
def run_dynamic_reminders():
    db = SessionLocal()
    try:
        today = datetime.now(timezone_wib).date()
        for sub in get_all_subscriptions(db):
            days_left = (sub.expires_at - today).days

            # Reset counter kalau sudah diperpanjang
            if days_left > 20:
                for col in ['reminder_count_h3', 'reminder_count_h2', 'reminder_count_h1', 'reminder_count_h0']:
                    setattr(sub, col, 0)
                db.commit()
                continue

            expire_str = sub.expires_at.strftime('%d %B %Y')

            if days_left == 3 and getattr(sub, 'reminder_count_h3', 0) < 2:
                msg = f"⚠️ PERINGATAN DINI\n\n{sub.name}\n{sub.url}\nExpire: {expire_str}\nTinggal 3 hari lagi — segera perpanjang!"
                asyncio.run(send_telegram_message(msg))
                sub.reminder_count_h3 += 1
                db.commit()

            elif days_left == 2 and getattr(sub, 'reminder_count_h2', 0) < 3:
                msg = f"🚨 MENDESAK!\n\n{sub.name}\n{sub.url}\nExpire: {expire_str}\nTINGGAL 2 HARI — HARI INI HARUS RENEW!"
                asyncio.run(send_telegram_message(msg))
                sub.reminder_count_h2 += 1
                db.commit()

            elif days_left == 1 and getattr(sub, 'reminder_count_h1', 0) < 5:
                msgs = [
                    f"🔥 BESOK MATI!\n\n{sub.name}\n{sub.url}\n<24 JAM LAGI!\nRENEW SEKARANG!",
                    f"🔥 H-1 BRO!!!\n\n{sub.name} besok nonaktif total!",
                    f"🔥 FINAL WARNING!\n\n{sub.name} tinggal jam lagi!",
                    f"🔥 RENEW HARI INI = SELAMAT!\n\n{sub.name}",
                    f"🔥 MALAM TERAKHIR!\n\nGa renew sekarang = besok mati permanen!",
                ]
                asyncio.run(send_telegram_message(msgs[getattr(sub, 'reminder_count_h1', 0)]))
                sub.reminder_count_h1 += 1
                db.commit()

            elif days_left <= 0 and getattr(sub, 'reminder_count_h0', 0) < 8:
                days_exp = "hari ini" if days_left == 0 else f"{abs(days_left)} hari lalu"
                msg = f"💀 SUDAH EXPIRE {days_exp.upper()}!\n\n{sub.name}\n{sub.url}\nRENEW SEKARANG sebelum dihapus permanen!"
                asyncio.run(send_telegram_message(msg))
                sub.reminder_count_h0 += 1
                db.commit()
    except Exception as e:
        logger.error(f"[REMINDER] Error: {e}")
    finally:
        db.close()

# Scheduler reminder otomatis tiap 7 menit + daily report jam 08:30 WIB
scheduler = BackgroundScheduler(timezone=timezone_wib)
scheduler.add_job(run_dynamic_reminders, "interval", minutes=7, next_run_time=datetime.now(timezone_wib))
scheduler.add_job(lambda: asyncio.run(send_daily_summary(get_all_subscriptions(SessionLocal()))), CronTrigger(hour=8, minute=30))
scheduler.start()

logger.info("RDR Hosting Reminder — BOOT SUKSES TOTAL — DATABASE AMAN — TELEGRAM GANAS — EDIT JALAN — HIDUP SELAMANYA — 03 DESEMBER 2025 ❤️")
