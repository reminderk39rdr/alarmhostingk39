from sqlalchemy.orm import Session
from sqlalchemy import and_
from datetime import date, timedelta
from models import Subscription
from schemas import SubscriptionCreate

def get_subscriptions(db: Session, skip: int = 0, limit: int = 100):
    return db.query(Subscription).offset(skip).limit(limit).all()

def create_subscription(db: Session, subscription: SubscriptionCreate):
    db_subscription = Subscription(
        name=subscription.name,
        url=subscription.url,
        expires_at=subscription.expires_at
    )
    db.add(db_subscription)
    db.commit()
    db.refresh(db_subscription)
    return db_subscription

def delete_subscription(db: Session, subscription_id: int):
    db_subscription = db.query(Subscription).filter(Subscription.id == subscription_id).first()
    if db_subscription:
        db.delete(db_subscription)
        db.commit()
    return db_subscription  # Mengembalikan objek jika ada, None jika tidak

def get_expiring_soon(db: Session, days_ahead: int):
    target_date = date.today() + timedelta(days=days_ahead)
    return db.query(Subscription).filter(Subscription.expires_at == target_date).all()
