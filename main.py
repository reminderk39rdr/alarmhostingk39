import os
import threading
import secrets
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
import re

from fastapi import FastAPI, Depends, HTTPException, Request, Form, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.exceptions import FastAPI
from fastapi.responses import JSONResponse

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from database import engine, SessionLocal, Base
from schemas import SubscriptionCreate
from models import Subscription
from crud import get_subscriptions, create_subscription, update_subscription, delete_subscription
from telegram_bot import send_telegram_message, send_full_list_trigger

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("K39")

app = FastAPI(title="K39 Reminder — HIDUP SELAMANYA 🔥")

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

timezone_wib = ZoneInfo("Asia/Jakarta")
security = HTTPBasic()

# AUTO MIGRASI KOLOM
Base.metadata.create_all(bind=engine)
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
except Exception as e:
    logger.error(f"[BOOT] Migrasi error: {e}")

def verify_credentials(credentials: HTTPBasicCredentials = Depends(security)):
    correct = secrets.compare_digest(credentials.username, os.getenv("ADMIN_USERNAME", "adminrdr")) and \
              secrets.compare_digest(credentials.password, os.getenv("ADMIN_PASSWORD", "j3las_kuat_39!"))
    if not correct:
        raise HTTPException(status_code=401, detail="Salah password bro", headers={"WWW-Authenticate": "Basic"})
    return credentials.username

def validate_input(name, url, expires_at, brand=None):
    name = name.strip()
    url = url.strip()
    expires_at = expires_at.strip()
    brand = brand.strip() if brand else None
    if len(name) < 2 or not url.startswith(('http://', 'https://')) or not re.match(r"^\d{2}/\d{2}/\d{4}$", expires_at):
        raise HTTPException(status_code=400, detail="Data salah format")
    from datetime import datetime
    exp_date = datetime.strptime(expires_at, "%m/%d/%Y").date()
    return name, url, exp_date, brand

@app.get("/", response_class=HTMLResponse)
async def root(request: Request, username: str = Depends(verify_credentials)):
    db = SessionLocal()
    try:
        subs = get_subscriptions(db)
    except:
        subs = []
    finally:
        db.close()
    return templates.TemplateResponse("index.html", {
        "request": request, "subs": subs, "today": datetime.now(timezone_wib).date(), "now": datetime.now(timezone_wib)
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
    return HTMLResponse("<h3 style='color:lime;text-align:center;padding:50px;background:#000'>FULL LIST SUDAH DIKIRIM KE TELEGRAM BRO! 🔥</h3>")

@app.get("/keep-alive")
async def keep_alive():
    return {"status": "HIDUP 100% BRO!", "time": datetime.now(timezone_wib).strftime("%d %B %Y %H:%M:%S WIB")}

scheduler = BackgroundScheduler(timezone=timezone_wib)
scheduler.add_job(lambda: asyncio.run(send_full_list_trigger()), "interval", minutes=420)  # optional auto list tiap 7 jam
scheduler.start()

logger.info("K39 REMINDER — HIDUP SELAMANYA 100% NO ERROR — 3 DESEMBER 2025 🔥🚀")