# main.py — K39 REMINDER FINAL ABADI — 03 DESEMBER 2025 🔥
import os
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
import secrets
import re

from fastapi import FastAPI, Depends, HTTPException, Request, Form, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError

from database import engine, SessionLocal, Base
from models import Subscription
from schemas import SubscriptionCreate
from crud import get_subscriptions, create_subscription, update_subscription, delete_subscription
from telegram_bot import send_full_list_trigger

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("K39")
timezone_wib = ZoneInfo("Asia/Jakarta")

app = FastAPI(title="K39 Reminder — HIDUP SELAMANYA 🔥")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

security = HTTPBasic()

# ===================================
# DATABASE CONNECTION TEST + AUTO MIGRATION
# ===================================
logger.info("[BOOT] Testing database connection...")
try:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    logger.info("[BOOT] Database connected successfully!")

    # Auto create table + kolom reminder
    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        inspector = inspect(engine)
        columns = [col['name'] for col in inspector.get_columns('subscription')]
        required = ['reminder_count_h3', 'reminder_count_h2', 'reminder_count_h1', 'reminder_count_h0', 'created_at']
        for col in required:
            if col not in columns:
                if col == 'created_at':
                    conn.execute(text("ALTER TABLE subscription ADD COLUMN created_at TIMESTAMP DEFAULT NOW()"))
                else:
                    conn.execute(text(f"ALTER TABLE subscription ADD COLUMN {col} INTEGER DEFAULT 0"))
                logger.info(f"[BOOT] Added column: {col}")

    logger.info("[BOOT] Database ready — all old data safe!")

except OperationalError as e:
    logger.critical(f"[BOOT] DATABASE CONNECTION FAILED: {e}")
    raise RuntimeError("Cannot connect to database. Check DATABASE_URL in Render!")
except Exception as e:
    logger.critical(f"[BOOT] Database setup error: {e}")
    raise

# ===================================
# AUTH
# ===================================
def verify_credentials(credentials: HTTPBasicCredentials = Depends(security)):
    correct_username = secrets.compare_digest(credentials.username, os.getenv("ADMIN_USERNAME", "adminrdr"))
    correct_password = secrets.compare_digest(credentials.password, os.getenv("ADMIN_PASSWORD", "j3las_kuat_39!"))
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Username/password salah bro!",
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

    if len(name) < 2:
        raise HTTPException(status_code=400, detail="Nama minimal 2 karakter")
    if not url.lower().startswith(('http://', 'https://')):
        raise HTTPException(status_code=400, detail="URL harus https:// atau http://")
    if not re.match(r"^\d{2}/\d{2}/\d{4}$", expires_at):
        raise HTTPException(status_code=400, detail="Format tanggal mm/dd/yyyy")

    try:
        from datetime import datetime
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
    except Exception as e:
        logger.error(f"[ROOT] DB Error: {e}")
        subs = []
    finally:
        db.close()

    return templates.TemplateResponse("index.html", {
        "request": request,
        "subs": subs,
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
        raise HTTPException(status_code=500, detail="Gagal simpan bro")
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
            raise HTTPException(status_code=404, detail="ID tidak ditemukan")
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
    return HTMLResponse("<h2 style='color:#00ff00;text-align:center;padding:100px;background:#000;font-family:sans-serif'>FULL LIST SUDAH DIKIRIM KE TELEGRAM BRO! 🔥<br><br><a href='/'>Kembali ke Dashboard</a></h2>")

@app.get("/keep-alive")
async def keep_alive():
    return {
        "status": "HIDUP 100% BRO!!!",
        "time": datetime.now(timezone_wib).strftime("%d %B %Y %H:%M:%S WIB"),
        "message": "K39 ga akan pernah mati lagi 🔥"
    }

@app.get("/db-status")
async def db_status():
    try:
        db = SessionLocal()
        count = db.query(Subscription).count()
        db.close()
        return {"status": "connected", "subscriptions": count}
    except Exception as e:
        return {"status": "error", "detail": str(e)}

logger.info("K39 REMINDER — BOOT SUKSES TOTAL — DATABASE TESTED — HIDUP SELAMANYA 100% — 03 DESEMBER 2025 🔥🚀💪")
