# main.py — RDR Hosting Reminder — VERSI ABADI PREMIUM — FINAL RULE BARZEV (SESSION EDITION)

import os
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
import secrets
import re
from collections import defaultdict
import asyncio

from fastapi import FastAPI, Depends, HTTPException, Request, Form, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from starlette.middleware.sessions import SessionMiddleware

from sqlalchemy import inspect, text
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from database import engine, SessionLocal, Base
from models import Subscription, LogEntry
from schemas import SubscriptionCreate
from crud import (
    get_subscriptions,
    get_all_subscriptions,
    create_subscription,
    update_subscription,
    delete_subscription,
    get_logs,
    add_log,
)

from telegram_bot import (
    send_telegram_message,
    send_full_list_trigger,
    send_daily_summary,
    send_reminders_3days,
    send_reminders_2days,
    send_reminders_1day_or_expired,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("RDR")

app = FastAPI(title="RDR Hosting Reminder", openapi_url="/openapi.json", docs_url="/docs")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

timezone_wib = ZoneInfo("Asia/Jakarta")

# ==========================
# SESSION MIDDLEWARE
# ==========================
SESSION_SECRET = os.getenv("SESSION_SECRET")
if not SESSION_SECRET:
    raise RuntimeError("SESSION_SECRET wajib di-set di Render env!")

app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    session_cookie="rdr_session",
    https_only=True,      # render pakai https
    same_site="lax",
)


# ===================================
# BOOT: DATABASE CONNECTION + MIGRATION
# ===================================
logger.info("[BOOT] Menghubungkan ke PostgreSQL...")
try:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    logger.info("[BOOT] Database terkoneksi — semua data aman selamanya!")

    Base.metadata.create_all(bind=engine)

    # migrasi kolom reminder kalau belum ada (existing kamu)
    with engine.begin() as conn:
        inspector = inspect(engine)
        columns = [col["name"] for col in inspector.get_columns("subscription")]
        required_cols = [
            "reminder_count_h3",
            "reminder_count_h2",
            "reminder_count_h1",
            "reminder_count_h0",
            "created_at",
        ]
        for col in required_cols:
            if col not in columns:
                if col == "created_at":
                    conn.execute(
                        text("ALTER TABLE subscription ADD COLUMN created_at TIMESTAMP DEFAULT NOW()")
                    )
                else:
                    conn.execute(text(f"ALTER TABLE subscription ADD COLUMN {col} INTEGER DEFAULT 0"))
                logger.info(f"[BOOT] Kolom {col} ditambahkan")

except Exception as e:
    logger.critical(f"[BOOT] GAGAL TERHUBUNG DATABASE: {e}")
    raise RuntimeError("Database connection failed — check DATABASE_URL")


# ===================================
# AUTH (SESSION)
# ===================================
def require_login(request: Request):
    if not request.session.get("logged_in"):
        raise HTTPException(status_code=302, headers={"Location": "/login"})


def verify_credentials(username: str, password: str) -> bool:
    correct_username = secrets.compare_digest(username, os.getenv("ADMIN_USERNAME", "adminrdr"))
    correct_password = secrets.compare_digest(password, os.getenv("ADMIN_PASSWORD", "j3las_kuat39!"))
    return correct_username and correct_password


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
    if not url.lower().startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="URL harus diawali http:// atau https://")
    if not re.match(r"^\d{2}/\d{2}/\d{4}$", expires_at):
        raise HTTPException(status_code=400, detail="Format tanggal mm/dd/yyyy")

    try:
        exp_date = datetime.strptime(expires_at, "%m/%d/%Y").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Tanggal tidak valid")

    return name, url, exp_date, brand


# ===================================
# LOGIN / LOGOUT ROUTES
# ===================================
@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    # kamu perlu bikin templates/login.html
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@app.post("/login")
async def login_action(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    if verify_credentials(username, password):
        request.session["logged_in"] = True
        request.session["username"] = username
        return RedirectResponse("/", status_code=303)

    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": "Username / Password salah"},
        status_code=401,
    )


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


# ===================================
# ROUTES (PROTECTED)
# ===================================
@app.get("/", response_class=HTMLResponse)
async def root(request: Request, _: None = Depends(require_login)):
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

        logs = get_logs(db, limit=200)

    except Exception as e:
        logger.error(f"[ROOT] DB Error: {e}")
        subs, grouped, expiring_soon, expired_count, logs = [], {}, 0, 0, []
        today = datetime.now(timezone_wib).date()
    finally:
        db.close()

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "subs": subs,
            "grouped": grouped,
            "today": today,
            "now": datetime.now(timezone_wib),
            "expiring_soon": expiring_soon,
            "expired_count": expired_count,
            "logs": logs,  # kamu render di dashboard
            "username": request.session.get("username", "admin"),
        },
    )


@app.post("/add")
async def add(
    request: Request,
    _: None = Depends(require_login),
    name: str = Form(...),
    url: str = Form(...),
    brand: str | None = Form(None),
    expires_at: str = Form(...),
):
    name, url, exp_date, brand = validate_input(name, url, expires_at, brand)
    db = SessionLocal()
    try:
        create_subscription(db, SubscriptionCreate(name=name, url=url, expires_at=exp_date, brand=brand))
        add_log(db, f"Add subscription: {name}", "INFO")
        db.commit()
    finally:
        db.close()
    return RedirectResponse("/", status_code=303)


@app.post("/update/{sub_id}")
async def update(
    request: Request,
    sub_id: int,
    _: None = Depends(require_login),
    name: str = Form(...),
    url: str = Form(...),
    brand: str | None = Form(None),
    expires_at: str = Form(...),
):
    name, url, exp_date, brand = validate_input(name, url, expires_at, brand)
    db = SessionLocal()
    try:
        old_sub = db.query(Subscription).filter(Subscription.id == sub_id).first()
        if not old_sub:
            raise HTTPException(status_code=404, detail="Subscription tidak ditemukan")

        old_exp = old_sub.expires_at

        result = update_subscription(
            db, sub_id, SubscriptionCreate(name=name, url=url, expires_at=exp_date, brand=brand)
        )
        db.commit()
        if not result:
            raise HTTPException(status_code=404, detail="Subscription tidak ditemukan")

        add_log(db, f"Update subscription: {name} -> {exp_date}", "INFO")

        # notif kalau diperpanjang
        if exp_date and old_exp and exp_date > old_exp:
            new_str = exp_date.strftime("%d %B %Y")
            await send_telegram_message(
                f"✅ <b>{name}</b> sudah diperpanjang sampai <b>{new_str}</b>."
            )
            add_log(db, f"Renewed: {name} to {new_str}", "WARN")

    finally:
        db.close()

    return RedirectResponse("/", status_code=303)


@app.post("/delete/{sub_id}")
async def delete(request: Request, sub_id: int, _: None = Depends(require_login)):
    db = SessionLocal()
    try:
        delete_subscription(db, sub_id)
        add_log(db, f"Delete subscription id={sub_id}", "WARN")
        db.commit()
    finally:
        db.close()
    return RedirectResponse("/", status_code=303)


# ===================================
# TRIGGER MANUAL
# ===================================
@app.get("/trigger")
async def trigger(_: None = Depends(require_login)):
    await send_full_list_trigger()
    return HTMLResponse(
        "<div style='text-align:center;padding:120px;background:#0a0a0f;color:#8b5cf6;font-family:system-ui'>"
        "<h2>List terbaru sudah dikirim ke Telegram ✅</h2>"
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
        "message": "Semua aman bro. Kamu sudah menang total.",
    }


# ===================================
# SCHEDULER OTOMATIS SESUAI RULE BARZEV
# ===================================
scheduler = BackgroundScheduler(timezone=timezone_wib)

# 1) Full list harian jam 09:00 WIB
scheduler.add_job(
    lambda: asyncio.run(send_daily_summary()),
    CronTrigger(hour=9, minute=0, timezone=timezone_wib),
    id="daily_summary_9am",
    replace_existing=True,
)

# 2) H-3 hari: 3x sehari (09:00, 15:00, 21:00)
for h in [9, 15, 21]:
    scheduler.add_job(
        lambda: asyncio.run(send_reminders_3days()),
        CronTrigger(hour=h, minute=0, timezone=timezone_wib),
        id=f"reminder_3days_{h}",
        replace_existing=True,
    )

# 3) H-2 hari: 6x sehari (tiap 4 jam)
for h in [0, 4, 8, 12, 16, 20]:
    scheduler.add_job(
        lambda: asyncio.run(send_reminders_2days()),
        CronTrigger(hour=h, minute=0, timezone=timezone_wib),
        id=f"reminder_2days_{h}",
        replace_existing=True,
    )

# 4) H-1 / H / expired: bising tiap 30 menit
for h in range(0, 24):
    scheduler.add_job(
        lambda: asyncio.run(send_reminders_1day_or_expired()),
        CronTrigger(hour=h, minute=0, timezone=timezone_wib),
        id=f"reminder_1day_{h}_00",
        replace_existing=True,
    )
    scheduler.add_job(
        lambda: asyncio.run(send_reminders_1day_or_expired()),
        CronTrigger(hour=h, minute=30, timezone=timezone_wib),
        id=f"reminder_1day_{h}_30",
        replace_existing=True,
    )

scheduler.start()
logger.info(
    "[SCHEDULER] Daily 09:00 + H-3 3x/hari + H-2 6x/hari + H-1/expired tiap 30 menit aktif."
)

logger.info("RDR Hosting Reminder — BOOT SUKSES TOTAL — ABADI SELAMANYA")
