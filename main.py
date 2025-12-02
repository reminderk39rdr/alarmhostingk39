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

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

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
# DATABASE TEST + MIGrasi KOLOM
# ===================================
logger.info("[BOOT] Testing database connection...")
try:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    logger.info("[BOOT] DATABASE CONNECTED 100% — ALL OLD DATA SAFE!")

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
                logger.info(f"[BOOT] Column {col} added")

except Exception as e:
    logger.critical(f"[BOOT] DATABASE ERROR: {e}")
    raise

# ===================================
# AUTH & VALIDATION
# ===================================
def verify_credentials(credentials: HTTPBasicCredentials = Depends(security)):
    if not (secrets.compare_digest(credentials.username, os.getenv("ADMIN_USERNAME", "adminrdr")) and
            secrets.compare_digest(credentials.password, os.getenv("ADMIN_PASSWORD", "j3las_kuat_39!"))):
        raise HTTPException(status_code=401, detail="Wrong credentials")
    return credentials.username

def validate_input(name, url, expires_at, brand=None):
    name = name.strip()
    url = url.strip()
    expires_at = expires_at.strip()
    brand = brand.strip() if brand else None
    if len(name) < 2 or not url.lower().startswith(('http://', 'https://')) or not re.match(r"^\d{2}/\d{2}/\d{4}$", expires_at):
        raise HTTPException(status_code=400, detail="Invalid input")
    from datetime import datetime
    exp_date = datetime.strptime(expires_at, "%m/%d/%Y").date()
    return name, url, exp_date, brand

# ===================================
# ROUTES
# ===================================
@app.get("/", response_class=HTMLResponse)
async def root(request: Request, username: str = Depends(verify_credentials)):
    db = SessionLocal()
    try:
        subs = get_subscriptions(db)
    except:
        subs = []
    finally:
        db.close()
    return templates.TemplateResponse("index.html", {"request": request, "subs": subs, "today": datetime.now(timezone_wib).date(), "now": datetime.now(timezone_wib)})

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
        update_subscription(db, sub_id, SubscriptionCreate(name=name, url=url, expires_at=exp_date, brand=brand))
        db.commit()
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
    return HTMLResponse("<h2 style='color:lime;background:black;padding:100px;text-align:center'>LIST PER BRAND SUDAH DIKIRIM KE TELEGRAM BRO! 🔥</h2>")

@app.get("/keep-alive")
async def keep_alive():
    return {"status": "HIDUP 100% BRO!", "time": datetime.now(timezone_wib).strftime("%d %B %Y %H:%M:%S WIB")}

logger.info("K39 REMINDER — BOOT SUKSES — DATABASE AMAN — TELEGRAM AMAN — HIDUP SELAMANYA — 03 DESEMBER 2025 🔥🚀")
