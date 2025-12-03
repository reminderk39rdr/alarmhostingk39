from sqlalchemy.orm import Session
from sqlalchemy import desc
from models import Subscription, LogEntry
from schemas import SubscriptionCreate
from datetime import datetime


# ========== Subscription ==========
def get_subscriptions(db: Session):
    return (
        db.query(Subscription)
        .filter(Subscription.is_archived == False)
        .order_by(Subscription.expires_at.asc())
        .all()
    )


def get_archived_subscriptions(db: Session):
    return (
        db.query(Subscription)
        .filter(Subscription.is_archived == True)
        .order_by(Subscription.expires_at.asc())
        .all()
    )


def get_all_subscriptions(db: Session, include_archived: bool = False):
    q = db.query(Subscription)
    if not include_archived:
        q = q.filter(Subscription.is_archived == False)
    return q.all()


def create_subscription(db: Session, sub: SubscriptionCreate):
    db_sub = Subscription(**sub.model_dump())
    db.add(db_sub)
    db.commit()
    db.refresh(db_sub)
    return db_sub


def update_subscription(db: Session, sub_id: int, sub: SubscriptionCreate):
    db_sub = db.query(Subscription).filter(Subscription.id == sub_id).first()
    if db_sub:
        for key, value in sub.model_dump().items():
            setattr(db_sub, key, value)
        db.commit()
        db.refresh(db_sub)
    return db_sub


def delete_subscription(db: Session, sub_id: int):
    db_sub = db.query(Subscription).filter(Subscription.id == sub_id).first()
    if db_sub:
        db.delete(db_sub)
        db.commit()
    return True


def archive_subscription(db: Session, sub_id: int, archived: bool = True):
    db_sub = db.query(Subscription).filter(Subscription.id == sub_id).first()
    if db_sub:
        db_sub.is_archived = archived
        db.commit()
        db.refresh(db_sub)
    return db_sub


def bulk_archive(db: Session, ids: list[int], archived: bool = True):
    if not ids:
        return
    db.query(Subscription).filter(Subscription.id.in_(ids)).update(
        {"is_archived": archived},
        synchronize_session=False,
    )
    db.commit()


def bulk_delete(db: Session, ids: list[int]):
    if not ids:
        return
    db.query(Subscription).filter(Subscription.id.in_(ids)).delete(
        synchronize_session=False
    )
    db.commit()


def quick_renew(db: Session, sub_id: int, add_days: int):
    sub = db.query(Subscription).filter(Subscription.id == sub_id).first()
    if not sub:
        return None
    sub.expires_at = sub.expires_at.fromordinal(sub.expires_at.toordinal() + add_days)
    db.commit()
    db.refresh(sub)
    return sub


def bulk_renew(db: Session, ids: list[int], add_days: int):
    if not ids:
        return
    subs = db.query(Subscription).filter(Subscription.id.in_(ids)).all()
    for s in subs:
        s.expires_at = s.expires_at.fromordinal(s.expires_at.toordinal() + add_days)
    db.commit()


def set_last_notified(db: Session, sub_id: int, stage: str):
    sub = db.query(Subscription).filter(Subscription.id == sub_id).first()
    if not sub:
        return
    sub.last_notified_at = datetime.utcnow()
    sub.last_notified_stage = stage
    db.commit()


# ========== Logs ==========
def add_log(db: Session, level: str, message: str):
    db.add(LogEntry(level=level, message=message))
    db.commit()


def get_latest_logs(db: Session, limit: int = 200):
    return (
        db.query(LogEntry)
        .order_by(desc(LogEntry.created_at))
        .limit(limit)
        .all()
    )
