import os, secrets, re, asyncio, csv, io, logging
from datetime import datetime
from zoneinfo import ZoneInfo
from collections import defaultdict

from fastapi import FastAPI, Depends, HTTPException, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
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
    get_subscriptions, get_archived_subscriptions, get_all_subscriptions,
    create_subscription, update_subscription, delete_subscription,
    archive_subscription, bulk_archive, bulk_delete,
    quick_renew, bulk_renew,
    get_latest_logs, add_log
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

SESSION_SECRET = os.getenv("SESSION_SECRET")
if not SESSION_SECRET:
    SESSION_SECRET = secrets.token_urlsafe(32)
    logger.warning("[BOOT] SESSION_SECRET kosong. Session reset tiap restart.")
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)

# ========= Health state =========
health_state = {
    "last_daily": None, "last_h3": None, "last_h2": None, "last_h1": None,
    "boot_time": datetime.now(timezone_wib),
}
def _touch_health(key: str):
    health_state[key] = datetime.now(timezone_wib)

# ===================================
# DB MIGRATION SAFE
# ===================================
logger.info("[BOOT] DB connect...")
with engine.connect() as conn:
    conn.execute(text("SELECT 1"))
Base.metadata.create_all(bind=engine)

with engine.begin() as conn:
    inspector = inspect(engine)
    sub_cols = [c["name"] for c in inspector.get_columns("subscription")]

    required_sub_cols = [
        "reminder_count_h3","reminder_count_h2","reminder_count_h1","reminder_count_h0",
        "created_at","is_archived","last_notified_at","last_notified_stage"
    ]
    for col in required_sub_cols:
        if col not in sub_cols:
            if col == "created_at":
                conn.execute(text("ALTER TABLE subscription ADD COLUMN created_at TIMESTAMP DEFAULT NOW()"))
            elif col == "is_archived":
                conn.execute(text("ALTER TABLE subscription ADD COLUMN is_archived BOOLEAN DEFAULT FALSE"))
            elif col == "last_notified_at":
                conn.execute(text("ALTER TABLE subscription ADD COLUMN last_notified_at TIMESTAMP NULL"))
            elif col == "last_notified_stage":
                conn.execute(text("ALTER TABLE subscription ADD COLUMN last_notified_stage VARCHAR NULL"))
            else:
                conn.execute(text(f"ALTER TABLE subscription ADD COLUMN {col} INTEGER DEFAULT 0"))
            logger.info(f"[BOOT] added subscription.{col}")

logger.info("[BOOT] DB OK ✅")


# ===================================
# AUTH
# ===================================
def require_login(request: Request):
    if not request.session.get("user"):
        raise HTTPException(status_code=401)
    return request.session["user"]

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "err": None})

@app.post("/login")
async def login_action(request: Request, username: str = Form(...), password: str = Form(...)):
    ok_user = secrets.compare_digest(username, os.getenv("ADMIN_USERNAME", "adminrdr"))
    ok_pass = secrets.compare_digest(password, os.getenv("ADMIN_PASSWORD", "j3las_kuat39!"))
    if not (ok_user and ok_pass):
        return templates.TemplateResponse("login.html", {"request": request, "err": "Username / password salah"})
    request.session["user"] = username
    return RedirectResponse("/", status_code=303)

@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


# ===================================
# VALIDATION (acuan lama)
# ===================================
def validate_input(name: str, url: str, expires_at: str, brand: str | None = None):
    name = name.strip(); url = url.strip(); expires_at = expires_at.strip()
    brand = brand.strip() if brand else None

    if len(name) < 3:
        raise HTTPException(status_code=400, detail="Nama minimal 3 karakter")
    if not url.lower().startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="URL harus diawali http:// / https://")
    if not re.match(r"^\d{2}/\d{2}/\d{4}$", expires_at):
        raise HTTPException(status_code=400, detail="Format tanggal mm/dd/yyyy")

    exp_date = datetime.strptime(expires_at, "%m/%d/%Y").date()
    return name, url, exp_date, brand


# ===================================
# ROUTES
# ===================================
@app.get("/", response_class=HTMLResponse)
async def root(request: Request, username: str = Depends(require_login)):
    db = SessionLocal()
    try:
        subs = get_subscriptions(db)
        archived = get_archived_subscriptions(db)

        grouped = defaultdict(list)
        for sub in subs:
            grouped[(sub.brand or "Tanpa Brand").strip().upper()].append(sub)
        grouped = dict(sorted(grouped.items()))

        today = datetime.now(timezone_wib).date()
        expiring_soon = sum(1 for s in subs if 0 < (s.expires_at - today).days <= 7)
        expired_count = sum(1 for s in subs if (s.expires_at - today).days < 0)
        logs = get_latest_logs(db, 200)
    finally:
        db.close()

    return templates.TemplateResponse("index.html", {
        "request": request, "username": username,
        "subs": subs, "archived": archived, "grouped": grouped,
        "today": today, "now": datetime.now(timezone_wib),
        "expiring_soon": expiring_soon, "expired_count": expired_count,
        "logs": logs, "health": health_state
    })

@app.post("/add")
async def add(username: str = Depends(require_login),
              name: str = Form(...), url: str = Form(...),
              brand: str | None = Form(None), expires_at: str = Form(...)):
    name, url, exp_date, brand = validate_input(name, url, expires_at, brand)
    db = SessionLocal()
    try:
        create_subscription(db, SubscriptionCreate(name=name, url=url, expires_at=exp_date, brand=brand))
        add_log(db, "INFO", f"Add: {name}")
    finally:
        db.close()
    return RedirectResponse("/", status_code=303)

@app.post("/update/{sub_id}")
async def update(sub_id: int, username: str = Depends(require_login),
                 name: str = Form(...), url: str = Form(...),
                 brand: str | None = Form(None), expires_at: str = Form(...)):
    name, url, exp_date, brand = validate_input(name, url, expires_at, brand)
    db = SessionLocal()
    try:
        old = db.query(Subscription).filter(Subscription.id == sub_id).first()
        if not old:
            raise HTTPException(status_code=404)
        old_exp = old.expires_at

        update_subscription(db, sub_id, SubscriptionCreate(name=name, url=url, expires_at=exp_date, brand=brand))
        add_log(db, "INFO", f"Update: {name}")

        # notif jika diperpanjang
        if exp_date > old_exp:
            new_str = exp_date.strftime("%d %B %Y")
            await send_telegram_message(f"✅ <b>{name}</b> sudah diperpanjang sampai <b>{new_str}</b>.")
            add_log(db, "INFO", f"Renew notify: {name} -> {new_str}")
    finally:
        db.close()
    return RedirectResponse("/", status_code=303)

@app.post("/delete/{sub_id}")
async def delete(sub_id: int, username: str = Depends(require_login)):
    db = SessionLocal()
    try:
        delete_subscription(db, sub_id)
        add_log(db, "WARN", f"Delete id={sub_id}")
    finally:
        db.close()
    return RedirectResponse("/", status_code=303)

@app.post("/archive/{sub_id}")
async def archive(sub_id: int, username: str = Depends(require_login)):
    db = SessionLocal()
    try:
        archive_subscription(db, sub_id, True)
        add_log(db, "INFO", f"Archive id={sub_id}")
    finally:
        db.close()
    return RedirectResponse("/", status_code=303)

@app.post("/unarchive/{sub_id}")
async def unarchive(sub_id: int, username: str = Depends(require_login)):
    db = SessionLocal()
    try:
        archive_subscription(db, sub_id, False)
        add_log(db, "INFO", f"Unarchive id={sub_id}")
    finally:
        db.close()
    return RedirectResponse("/", status_code=303)

@app.post("/bulk/archive")
async def bulk_archive_route(request: Request, username: str = Depends(require_login)):
    form = await request.form()
    ids = [int(x) for x in form.getlist("ids")]
    if ids:
        db = SessionLocal()
        try:
            bulk_archive(db, ids, True)
            add_log(db, "INFO", f"Bulk archive {ids}")
        finally:
            db.close()
    return RedirectResponse("/", status_code=303)

@app.post("/bulk/delete")
async def bulk_delete_route(request: Request, username: str = Depends(require_login)):
    form = await request.form()
    ids = [int(x) for x in form.getlist("ids")]
    if ids:
        db = SessionLocal()
        try:
            bulk_delete(db, ids)
            add_log(db, "WARN", f"Bulk delete {ids}")
        finally:
            db.close()
    return RedirectResponse("/", status_code=303)

@app.post("/bulk/renew/{days}")
async def bulk_renew_route(days: int, request: Request, username: str = Depends(require_login)):
    form = await request.form()
    ids = [int(x) for x in form.getlist("ids")]
    if ids:
        db = SessionLocal()
        try:
            bulk_renew(db, ids, days)
            add_log(db, "INFO", f"Bulk renew {ids} +{days}d")
        finally:
            db.close()
    return RedirectResponse("/", status_code=303)

@app.post("/quick-renew/{sub_id}/{days}")
async def quick_renew_route(sub_id: int, days: int, username: str = Depends(require_login)):
    db = SessionLocal()
    try:
        quick_renew(db, sub_id, days)
        add_log(db, "INFO", f"Quick renew id={sub_id} +{days}d")
    finally:
        db.close()
    return RedirectResponse("/", status_code=303)

@app.get("/export")
async def export_csv(username: str = Depends(require_login)):
    db = SessionLocal()
    try:
        subs = get_all_subscriptions(db, include_archived=True)
    finally:
        db.close()

    output = io.StringIO()
    w = csv.writer(output)
    w.writerow(["id","name","url","brand","expires_at","is_archived"])
    for s in subs:
        w.writerow([s.id, s.name, s.url, s.brand or "",
                    s.expires_at.strftime("%m/%d/%Y"),
                    "1" if s.is_archived else "0"])
    output.seek(0)
    return StreamingResponse(output, media_type="text/csv",
        headers={"Content-Disposition":"attachment; filename=rdr_subscriptions.csv"})

@app.post("/import")
async def import_csv(file: UploadFile = File(...), username: str = Depends(require_login)):
    content = (await file.read()).decode("utf-8", errors="ignore")
    reader = csv.DictReader(io.StringIO(content))

    db = SessionLocal()
    try:
        for row in reader:
            name = (row.get("name") or "").strip()
            url = (row.get("url") or "").strip()
            brand = (row.get("brand") or "").strip() or None
            exp_str = (row.get("expires_at") or "").strip()
            if not name or not url or not exp_str:
                continue
            _, _, exp_date, brand = validate_input(name, url, exp_str, brand)

            sid = row.get("id")
            if sid and sid.isdigit():
                existing = db.query(Subscription).filter(Subscription.id == int(sid)).first()
                if existing:
                    existing.name = name
                    existing.url = url
                    existing.brand = brand
                    existing.expires_at = exp_date
                    existing.is_archived = row.get("is_archived") == "1"
                    continue

            create_subscription(db, SubscriptionCreate(name=name, url=url, expires_at=exp_date, brand=brand))

        db.commit()
        add_log(db, "INFO", f"CSV import success: {file.filename}")
    finally:
        db.close()

    return RedirectResponse("/", status_code=303)

@app.get("/telegram-test")
async def telegram_test(username: str = Depends(require_login)):
    ok = await send_telegram_message("✅ <b>Telegram test OK</b>\nRDR siap jalan bro.")
    db = SessionLocal()
    try:
        add_log(db, "INFO", f"Telegram test ok={ok}")
    finally:
        db.close()
    return RedirectResponse("/", status_code=303)

@app.get("/trigger")
async def trigger(username: str = Depends(require_login)):
    await send_full_list_trigger(stage="MANUAL")
    return RedirectResponse("/", status_code=303)

@app.get("/health")
async def health(username: str = Depends(require_login)):
    return {k: str(v) for k, v in health_state.items()}


# ===================================
# SCHEDULER JOBS
# ===================================
scheduler = BackgroundScheduler(timezone=timezone_wib)

def wrap_job(coro, key):
    def _runner():
        _touch_health(key)
        asyncio.run(coro())
    return _runner

# daily 09:00 WIB
scheduler.add_job(
    wrap_job(send_daily_summary, "last_daily"),
    CronTrigger(hour=9, minute=0, timezone=timezone_wib),
    id="daily_summary_9am",
    replace_existing=True,
)

# H-3: 3x sehari
for h in [9, 15, 21]:
    scheduler.add_job(
        wrap_job(send_reminders_3days, "last_h3"),
        CronTrigger(hour=h, minute=0, timezone=timezone_wib),
        id=f"reminder_3days_{h}",
        replace_existing=True,
    )

# H-2: 6x sehari (tiap 4 jam)
for h in [0, 4, 8, 12, 16, 20]:
    scheduler.add_job(
        wrap_job(send_reminders_2days, "last_h2"),
        CronTrigger(hour=h, minute=0, timezone=timezone_wib),
        id=f"reminder_2days_{h}",
        replace_existing=True,
    )

# H-1 / expired: tiap 30 menit
for h in range(0, 24):
    scheduler.add_job(
        wrap_job(send_reminders_1day_or_expired, "last_h1"),
        CronTrigger(hour=h, minute=0, timezone=timezone_wib),
        id=f"reminder_1day_{h}_00",
        replace_existing=True,
    )
    scheduler.add_job(
        wrap_job(send_reminders_1day_or_expired, "last_h1"),
        CronTrigger(hour=h, minute=30, timezone=timezone_wib),
        id=f"reminder_1day_{h}_30",
        replace_existing=True,
    )

scheduler.start()
logger.info("[SCHEDULER] OK ✅")
