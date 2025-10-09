from sqlalchemy.orm import Session
from . import models, schemas
from datetime import date, timedelta

def get_subscriptions(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.Subscription).offset(skip).limit(limit).all()

def create_subscription(db: Session, subscription: schemas.SubscriptionCreate):
    db_sub = models.Subscription(**subscription.model_dump())
    db.add(db_sub)
    db.commit()
    db.refresh(db_sub)
    return db_sub

def delete_subscription(db: Session, sub_id: int):
    db_sub = db.query(models.Subscription).filter(models.Subscription.id == sub_id).first()
    if db_sub:
        db.delete(db_sub)
        db.commit()
    return db_sub

def get_expiring_soon(db: Session, days_ahead: int):
    target = date.today() + timedelta(days=days_ahead)
    return db.query(models.Subscription).filter(models.Subscription.expires_at == target).all()