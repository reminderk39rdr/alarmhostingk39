from sqlalchemy.orm import Session
from models import Subscription
from schemas import SubscriptionCreate

def get_subscriptions(db: Session, skip: int = 0, limit: int = 100):
    return db.query(Subscription).offset(skip).limit(limit).all()

def create_subscription(db: Session, subscription: SubscriptionCreate):
    db_sub = Subscription(**subscription.model_dump())
    db.add(db_sub)
    db.commit()
    db.refresh(db_sub)
    return db_sub

def delete_subscription(db: Session, subscription_id: int):
    db_sub = db.query(Subscription).filter(Subscription.id == subscription_id).first()
    if db_sub:
        db.delete(db_sub)
        db.commit()
    return db_sub

def get_expiring_soon(db: Session, days_ahead: int):
    from datetime import date, timedelta
    target = date.today() + timedelta(days=days_ahead)
    return db.query(Subscription).filter(Subscription.expires_at == target).all()