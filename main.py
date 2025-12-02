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
from schemas import SubscriptionCreate   # <<< PASTIKAN schemas.py ADA!!!
from models import Subscription
from crud import get_subscriptions, get_all_subscriptions, create_subscription, update_subscription, delete_subscription
from telegram_bot import send_telegram_message, send_daily_summary

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# =============================================
# DATABASE AUTO MIGRATION KOLOM
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
except Exception as e:
    logger.error(f"[BOOT] Gagal migrasi kolom: {e}")

# =============================================
# KONFIG
# =============================================
timezone_wib = ZoneInfo("Asia/Jakarta")
security = HTTPBasic()
templates = Jinja2Templates(directory="templates")

def verify_credentials(credentials: HTTPBasicCredentials = Depends(security)):
    correct_username = secrets.compare_digest(credentials.username, os.getenv("ADMIN_USERNAME", "adminrdr"))
    correct_password = secrets.compare_digest(credentials.password, os.getenv("ADMIN_PASSWORD", "j3las_kuat_39!"))
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Username/password salah",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

# =============================================
# VALIDATION
# =============================================
def validate_input(name: str, url: str, expires_at: str, brand: str | None = None):
    name = name.strip()
    url = url.strip()
    expires_at = expires_at.strip()
    brand = brand.strip() if brand else None

    if len(name) < 2:
        raise HTTPException(status_code=400, detail="Nama minimal 2 karakter")
    if not url.lower().startswith(('http://', 'https://')):
        raise HTTPException(status_code=400, detail="URL harus pakai http/https")
    if not re.match(r"^\d{2}/\d{2}/\d{4}$", expires_at):
        raise HTTPException(status_code=400, detail="Format tanggal mm/dd/yyyy")

    try:
        exp_date = datetime.strptime(expires_at, "%m/%d/%Y").date()
        if exp_date < date.today():
            raise HTTPException(status_code=400, detail="Tanggal ga boleh sudah lewat")
    except ValueError:
        raise HTTPException(status_code=400, detail="Tanggal invalid")

    return name, url, exp_date, brand

# =============================================
# TELEGRAM HELPER
# =============================================
async def safe_send(msg: str):
    try:
        await send_telegram_message(msg)
    except Exception as e:
        logger.error(f"Telegram error: {e}")

def send_in_thread(msg: str):
    threading.Thread(target=lambda: asyncio.run(safe_send(msg)), daemon=True).start()

# =============================================
# REMINDER ENGINE — SUPER GANAS (tiap 7 menit)
# =============================================
def run_dynamic_reminders():
    db = SessionLocal()
    try:
        today = datetime.now(timezone_wib).date()
        for sub in get_all_subscriptions(db):
            days_left = (sub.expires_at - today).days

            # Reset counter kalau diperpanjang
            if days_left > 20:
                if any(getattr(sub, f'reminder_count_h{h}', 0) for h in [3,2,1,0]):
                    for h in [3,2,1,0]:
                        setattr(sub, f'reminder_count_h{h}', 0)
                    db.commit()

            expire_str = sub.expires_at.strftime('%d %B %Y')

            if days_left == 3 and getattr(sub, 'reminder_count_h3', 0) < 2:
                send_in_thread(f"⚠️ PERINGATAN\n\n*{sub.name}* tinggal 3 hari!\n{ sub.url }\nExpire: {expire_str}\n\nPerpanjang sekarang!")
                sub.reminder_count_h3 += 1
                db.commit()

            elif days_left == 2 and getattr(sub, 'reminder_count_h2', 0) < 3:
                send_in_thread(f"🚨 MENDESAK!\n\n*{sub.name}* tinggal 2 hari!\n{ sub.url }\nExpire: {expire_str}\n\nHARI INI HARUS RENEW!")
                sub.reminder_count_h2 += 1
                db.commit()

            elif days_left == 1 and getattr(sub, 'reminder_count_h1', 0) < 5:
                msgs = [
                    f"🔥 BESOK MATI!\n\n*{sub.name}* < 24 jam lagi!\n{ sub.url }\nExpire: {expire_str}\n\nRENEW SEKARANG ATAU DATA ILANG!",
                    f"🔥 H-1 BRO!!!\n\n*{sub.name}* besok nonaktif total!\n{ sub.url }",
                    f"🔥 FINAL CALL!\n\n*{sub.name}* tinggal jam lagi!\n{ sub.url }\nJANGAN NYESAL!",
                    f"🔥 RENEW HARI INI = SELAMAT!\n\n*{sub.name}*\n{ sub.url }",
                    f"🔥 MALAM TERAKHIR!\n\nGa renew sekarang = besok mati!\n{ sub.url }",
                ]
                send_in_thread(msgs[getattr(sub, 'reminder_count_h1', 0)])
                sub.reminder_count_h1 += 1
                db.commit()

            elif days_left <= 0 and getattr(sub, 'reminder_count_h0', 0) < 8:
                days_exp = "hari ini" if days_left == 0 else f"{abs(days_left)} hari lalu"
                send_in_thread(f"💀 SUDAH EXPIRE {days_exp.upper()}!\n\n*{sub.name}* mati!\n{ sub.url }\nExpire: {expire_str}\n\nRENEW SEKARANG SEBELUM DIHAPUS PERMANEN!")
                sub.reminder_count_h0 += 1
                db.commit()
    except Exception as e:
        logger.error(f"Reminder error: {e}")
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
# SCHEDULER
# =============================================
scheduler = BackgroundScheduler(timezone=timezone_wib)
scheduler.add_job(run_dynamic_reminders, "interval", minutes=7, next_run_time=datetime.now(timezone_wib))
scheduler.add_job(daily_job, CronTrigger(hour=8, minute=30))
scheduler.start()

# =============================================
# FASTAPI APP
# =============================================
app = FastAPI(title="K39 Reminder — HIDUP SELAMANYA")

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/", response_class=HTMLResponse)
async def root(request: Request, username: str = Depends(verify_credentials)):
    db = SessionLocal()
    try:
        subs = get_subscriptions(db)
    finally:
        db.close()
    return templates.TemplateResponse("index.html", {"request": request, "subs": subs, "today": datetime.now(timezone_wib).date()})

# ... (routes add, update, delete sama seperti sebelumnya - aku persingkat biar ga kepanjangan, pakai yang versi sebelumnya)

@app.get("/keep-alive")
async def keep_alive():
    return {"status": "HIDUP BRO 100%!!!", "time": datetime.now(timezone_wib).strftime("%d %B %Y %H:%M:%S WIB"), "message": "K39 ga akan pernah mati lagi 🔥"}

logger.info("K39 Reminder — BOOT SUKSES TOTAL — HIDUP SELAMANYA! 🚀🔥")