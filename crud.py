# crud.py

from sqlalchemy.orm import Session
from models import Subscription
from schemas import SubscriptionCreate

def get_subscriptions(db: Session):
    return db.query(Subscription).all()

def get_all_subscriptions(db: Session):
    return db.query(Subscription).all()

def create_subscription(db: Session, sub: SubscriptionCreate):
    db_sub = Subscription(**sub.dict())
    db.add(db_sub)
    db.commit()
    db.refresh(db_sub)
    return db_sub

def update_subscription(db: Session, sub_id: int, sub_update: SubscriptionCreate):
    db_sub = db.query(Subscription).filter(Subscription.id == sub_id).first()
    if db_sub:
        for key, value in sub_update.dict(exclude_unset=True).items():
            setattr(db_sub, key, value)
        db.commit()
        db.refresh(db_sub)
    return db_sub

def delete_subscription(db: Session, sub_id: int):
    db_sub = db.query(Subscription).filter(Subscription.id == sub_id).first()
    if db_sub:
        db.delete(db_sub)
        db.commit()
    return db_sub