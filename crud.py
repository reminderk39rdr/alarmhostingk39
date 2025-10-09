# crud.py
from sqlalchemy.orm import Session
from datetime import date, timedelta, datetime
from models import Subscription
from schemas import SubscriptionCreate
from telegram_bot import send_telegram_message, send_daily_summary
import asyncio
import threading

def get_subscriptions(db: Session, skip: int = 0, limit: int = 100):
    return db.query(Subscription).offset(skip).limit(limit).all()

def create_subscription(db: Session, subscription_: SubscriptionCreate):
    db_sub = Subscription(**subscription_.model_dump())
    # Tambahkan kolom untuk menyimpan waktu penambahan
    db_sub.created_at = datetime.now()
    db.add(db_sub)
    db.commit()
    db.refresh(db_sub)

    # --- Kirim Daftar Lengkap dengan Penanda (BARU DITAMBAHKAN) ---
    all_subscriptions = get_subscriptions(db)
    send_new_list_notification(all_subscriptions, db_sub.id) # Kirim notifikasi dengan penanda
    # --------------------------

    # --- Real-time check saat add ---
    today = date.today()
    if db_sub.expires_at == today + timedelta(days=1):
        msg = f"🔥 URGENT: '{db_sub.name}' ({db_sub.url}) expires TOMORROW! ({db_sub.expires_at})"
        _send_telegram_async(msg)
        db_sub.reminder_count_h1 = 1
        db_sub.last_reminder_time = datetime.now()
        db_sub.last_reminder_type = 'h1'
        db.commit()
    elif db_sub.expires_at == today + timedelta(days=3):
        msg = f"🚨 Reminder: '{db_sub.name}' ({db_sub.url}) expires in 3 days! ({db_sub.expires_at})"
        _send_telegram_async(msg)
        db_sub.reminder_count_h3 = 1
        db_sub.last_reminder_time = datetime.now()
        db_sub.last_reminder_type = 'h3'
        db.commit()
    # --------------------------

    return db_sub

def update_subscription(db: Session, subscription_id: int, subscription_: SubscriptionCreate):
    db_sub = db.query(Subscription).filter(Subscription.id == subscription_id).first()
    if db_sub:
        old_expires_at = db_sub.expires_at
        for field, value in subscription_.model_dump().items():
            setattr(db_sub, field, value)
        db.commit()
        db.refresh(db_sub)

        # --- Real-time check saat update ---
        if old_expires_at != db_sub.expires_at:
            today = date.today()
            if db_sub.expires_at == today + timedelta(days=1):
                msg = f"🔥 URGENT: '{db_sub.name}' ({db_sub.url}) expires TOMORROW! ({db_sub.expires_at})"
                _send_telegram_async(msg)
                db_sub.reminder_count_h3 = 0
                db_sub.reminder_count_h0 = 0
                db_sub.reminder_count_h1 = 1
                db_sub.last_reminder_time = datetime.now()
                db_sub.last_reminder_type = 'h1'
            elif db_sub.expires_at == today + timedelta(days=3):
                msg = f"🚨 Reminder: '{db_sub.name}' ({db_sub.url}) expires in 3 days! ({db_sub.expires_at})"
                _send_telegram_async(msg)
                db_sub.reminder_count_h1 = 0
                db_sub.reminder_count_h0 = 0
                db_sub.reminder_count_h3 = 1
                db_sub.last_reminder_time = datetime.now()
                db_sub.last_reminder_type = 'h3'
            elif db_sub.expires_at < today:
                 db_sub.reminder_count_h3 = 0
                 db_sub.reminder_count_h1 = 0
                 db_sub.reminder_count_h0 = 0
                 db_sub.last_reminder_time = None
                 db_sub.last_reminder_type = None
            db.commit()
        # --------------------------

    return db_sub

def delete_subscription(db: Session, subscription_id: int):
    db_sub = db.query(Subscription).filter(Subscription.id == subscription_id).first()
    if db_sub:
        db.delete(db_sub)
        db.commit()
    return db_sub

def get_expiring_soon(db: Session, days_ahead: int):
    target_date = date.today() + timedelta(days=days_ahead)
    return db.query(Subscription).filter(Subscription.expires_at == target_date).all()

def get_all_subscriptions(db: Session):
    """Fungsi untuk mendapatkan semua subscription, digunakan oleh scheduler."""
    return db.query(Subscription).all()

# --- Fungsi Baru untuk Kirim Notifikasi Daftar Lengkap ---
def send_new_list_notification(all_subscriptions, new_subscription_id):
    """
    Kirim daftar lengkap subscription ke Telegram dengan penanda (BARU DITAMBAHKAN).
    all_subscriptions: list objek Subscription SQLAlchemy
    new_subscription_id: ID subscription yang baru ditambahkan
    """
    if not all_subscriptions:
        # Jika tidak ada data, tidak perlu kirim
        return

    today = date.today()
    message_lines = ["📋 <b>Daftar Lengkap Subscription (Update Baru):</b>"]
    for sub in all_subscriptions:
        expires_at = sub.expires_at
        days_left = (expires_at - today).days
        if days_left > 0:
            status = f"{days_left} hari lagi"
        elif days_left == 0:
            status = "<b>Expired HARI INI!</b>"
        else:
            status = f"<b>Expired {abs(days_left)} hari lalu!</b>"

        # Tambahkan penanda (BARU DITAMBAHKAN) jika ID cocok
        new_tag = " <i>(BARU DITAMBAHKAN)</i>" if sub.id == new_subscription_id else ""

        # Format waktu penambahan
        created_time_str = sub.created_at.strftime('%d %b %Y %H:%M:%S') if sub.created_at else "Tidak diketahui"

        message_lines.append(
            f"\n• <b>{sub.name}</b>{new_tag}\n"
            f"  <code>{sub.url}</code>\n"
            f"  <i>Expired:</i> {expires_at.strftime('%d %b %Y')}\n"
            f"  <i>Sisa Waktu:</i> {status}\n"
            f"  <i>Ditambahkan:</i> {created_time_str}"
        )

    full_message = "\n".join(message_lines)
    # Kirim pesan
    import asyncio
    def run_async():
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(send_telegram_message(full_message))
        finally:
            loop.close()

    thread = threading.Thread(target=run_async)
    thread.start()
# ---

# Fungsi bantu untuk mengirim notifikasi async dari sync context
def _send_telegram_async(msg: str):
    def run_async():
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(send_telegram_message(msg))
        finally:
            loop.close()

    thread = threading.Thread(target=run_async)
    thread.start()
