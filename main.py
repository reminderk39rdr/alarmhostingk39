# main.py — RDR Hosting Reminder — FINAL ABADI 03 DESEMBER 2025
import os
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
import secrets
import re
from collections import defaultdict

from fastapi import FastAPI, Depends, HTTPException, Request, Form, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError

from database import engine, SessionLocal, Base
from models import Subscription
from schemas import SubscriptionCreate
from crud import get_subscriptions, get_all_subscriptions, create_subscription, update_subscription, delete_subscription
from telegram_bot import send_full_list_trigger

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
logger = logging.getLogger("RDR")

app = FastAPI(title="RDR Hosting Reminder")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

timezone_wib = ZoneInfo("Asia/Jakarta")
security = HTTPBasic()

# ===================================
# DATABASE BOOT TEST + AUTO MIGRATION (PALING AMAN)
# ===================================
logger.info("[BOOT] Connecting to database...")
try:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    logger.info("[BOOT] Database connected successfully — all old data safe!")

    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        inspector = inspect(engine)
        columns = [col['name'] for col in inspector.get_columns('subscription')]
        for col in ['reminder_count_h3', 'reminder_count_h2', 'reminder_count_h1', 'reminder_count_h0', 'created_at']:
            if col not in columns:
                if col == 'created_at':
                    conn.execute(text("ALTER TABLE subscription ADD COLUMN created_at TIMESTAMP DEFAULT NOW()"))
                else:
                    conn.execute(text(f"ALTER TABLE subscription ADD COLUMN {col} INTEGER DEFAULT 0"))
                logger.info(f"[BOOT] Added column: {col}")
except Exception as e:
    logger.critical(f"[BOOT] DATABASE FAILED: {e}")
    raise RuntimeError("Database connection failed — check DATABASE_URL")

# ===================================
# AUTH & VALIDATION
# ===================================
def verify_credentials(credentials: HTTPBasicCredentials = Depends(security)):
    correct = (secrets.compare_digest(credentials.username, os.getenv("ADMIN_USERNAME", "adminrdr")) and
               secrets.compare_digest(credentials.password, os.getenv("ADMIN_PASSWORD", "j3las_kuat_39!")))
    if not correct:
        raise HTTPException(status_code=401, detail="Invalid credentials", headers={"WWW-Authenticate": "Basic"})
    return credentials.username

def validate_input(name: str, url: str, expires_at: str, brand: str | None = None):
    name = name.strip()
    url = url.strip()
    expires_at = expires_at.strip()
    brand = brand.strip() if brand else None

    if len(name) < 2:
        raise HTTPException(status_code=400, detail="Name too short")
    if not url.lower().startswith(('http://', 'https://')):
        raise HTTPException(status_code=400, detail="URL must start with http/https")
    if not re.match(r"^\d{2}/\d{2}/\d{4}$", expires_at):
        raise HTTPException(status_code=400, detail="Date format mm/dd/yyyy")
    try:
        exp_date = datetime.strptime(expires_at, "%m/%d/%Y").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date")
    return name, url, exp_date, brand

# ===================================
# ROUTES
# ===================================
@app.get("/", response_class=HTMLResponse)
async def root(request: Request, username: str = Depends(verify_credentials)):
    db = SessionLocal()
    try:
        subs = get_subscriptions(db)

        # Grouping aman di Python (no Jinja error lagi)
        grouped = defaultdict(list)
        for sub in subs:
            brand_key = (sub.brand or "No Brand").strip().upper()
            grouped[brand_key].append(sub)
        grouped = dict(sorted(grouped.items()))  # sort brand alphabetically
    except Exception as e:
        logger.error(f"[ROOT] DB error: {e}")
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
        raise HTTPException(status_code=500, detail="Failed to add")
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
            raise HTTPException(status_code=404, detail="Not found")
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
    return HTMLResponse("<div style='text-align:center;padding:100px;font-family:sans-serif;background:#000;color:#8b5cf6'><h2>List per brand telah dikirim ke Telegram</h2><p><a href='/' style='color:#fff'>← Kembali ke Dashboard</a></p></div>")

@app.get("/keep-alive")
async def keep_alive():
    return {
        "status": "RDR Hosting Reminder — HIDUP 100%",
        "time": datetime.now(timezone_wib).strftime("%d %B %Y %H:%M:%S WIB"),
        "data_count": len(get_all_subscriptions(SessionLocal()))
    }

logger.info("RDR Hosting Reminder — BOOT SUKSES — DATABASE AMAN — TELEGRAM AMAN — HIDUP SELAMANYA — 03 DESEMBER 2025")
