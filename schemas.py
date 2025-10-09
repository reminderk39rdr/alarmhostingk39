# schemas.py
from pydantic import BaseModel
from datetime import date, datetime
from typing import Optional

class SubscriptionBase(BaseModel):
    name: str
    url: str
    expires_at: date

class SubscriptionCreate(SubscriptionBase):
    pass

class Subscription(SubscriptionBase):
    id: int
    # Tambahkan field tracking ke schema response
    reminder_count_h3: int
    reminder_count_h1: int
    reminder_count_h0: int
    last_reminder_time: Optional[datetime]
    last_reminder_type: Optional[str]
    # Tambahkan field created_at
    created_at: Optional[datetime]

    class Config:
        from_attributes = True
