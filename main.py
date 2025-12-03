# main.py — RDR Hosting Reminder — VERSI ABADI PREMIUM — 03 DESEMBER 2025
import os
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
import secrets
import re
from collections import defaultdict
import asyncio
from fastapi import FastAPI, Depends, HTTPException, Request, Form, status
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
from telegram_bot import send_telegram_message, send_daily_summary  # pastikan fungsi ini ada

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
# BOOT: DATABASE CONNECTION + MIGRATION
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
# ROUTES
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
        today = datetime.now(timezone_wib).date()
        expiring_soon = sum(1 for sub in subs if 0 < (sub.expires_at - today).days <= 7)
        expired_count = sum(1 for sub in subs if (sub.expires_at - today).days < 0)
    except Exception as e:
        logger.error(f"[ROOT] DB Error: {e}")
        subs, grouped, expiring_soon, expired_count = [], {}, 0, 0
    finally:
        db.close()

    return templates.TemplateResponse("index.html", {
        "request": request,
        "subs": subs,
        "grouped": grouped,
        "today": today,
        "now": datetime.now(timezone_wib),
        "expiring_soon": expiring_soon,
        "expired_count": expired_count
    })

@app.post("/add")
async def add(username: str = Depends(verify_credentials), name: str = Form(...), url: str = Form(...), brand: str | None = Form(None), expires_at: str = Form(...)):
    name, url, exp_date, brand = validate_input(name, url, expires_at, brand)
    db = SessionLocal()
    try:
        create_subscription(db, SubscriptionCreate(name=name, url=url, expires_at=exp_date, brand=brand))
        db.commit()
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

# ===================================
# TRIGGER: SEND FULL LIST TO TELEGRAM (SESUAI PERMINTAAN)
# ===================================
@app.get("/trigger")
async def trigger(username: str = Depends(verify_credentials)):
    db = SessionLocal()
    try:
        subs = get_all_subscriptions(db)
        today = datetime.now(timezone_wib).date()
        now = datetime.now(timezone_wib)

        if not subs:
            await send_telegram_message("Belum ada subscription bro!")
            return HTMLResponse("<h2 style='text-align:center;padding:100px;color:#8b5cf6;font-family:system-ui'>Belum ada subscription bro!<br><a href='/' style='color:#fff'>← Kembali</a></h2>")

        grouped = defaultdict(list)
        for sub in subs:
            key = (sub.brand or "Tanpa Brand").strip().upper()
            grouped[key].append(sub)

        message = f"Our Hosting List\n{now.strftime('%d %B %Y - %H:%M WIB')}\n\n"

        for brand, items in sorted(grouped.items()):
            message += f"{brand}\n"
            for i, sub in enumerate(items, 1):
                days = (sub.expires_at - today).days
                skull = " Skull" if days < 0 else ""
                rocket = " Rocket" if days > 30 else ""
                message += f"{i}. {sub.name}\n   {sub.url}\n   Expire: {sub.expires_at.strftime('%d %B %Y')} ({days} hari lagi){skull}{rocket}\n"
            message += "─" * 20 + "\n"

        message += f"\nTOTAL: {len(subs)} SUBSCRIPTION"

        await send_telegram_message(message)
    finally:
        db.close()

    return HTMLResponse(
        "<div style='text-align:center;padding:120px;background:#0a0a0f;color:#8b5cf6;font-family:system-ui'>"
        "<h2>List per brand telah dikirim ke Telegram</h2>"
        "<p><a href='/' style='color:#fff;text-decoration:none;font-size:1.2rem'>← Kembali ke Dashboard</a></p></div>"
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
# REMINDER OTOMATIS (DIPINDAH KE telegram_bot.py agar aman dari asyncio.run() di thread)
# ===================================
def run_dynamic_reminders():
    asyncio.run(send_daily_summary())  # atau panggil fungsi dari telegram_bot.py

scheduler = BackgroundScheduler(timezone=timezone_wib)
scheduler.add_job(run_dynamic_reminders, "interval", minutes=7, next_run_time=datetime.now(timezone_wib))
scheduler.add_job(lambda: asyncio.run(send_daily_summary()), CronTrigger(hour=8, minute=30, timezone=timezone_wib))
scheduler.start()

logger.info("RDR Hosting Reminder — BOOT SUKSES TOTAL — OUR HOSTING LIST SIAP — BRAND SUPPORT — MOBILE CANTIK — ABADI SELAMANYA — 03 DESEMBER 2025")
