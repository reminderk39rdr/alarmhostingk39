# schemas.py

from pydantic import BaseModel
from datetime import date

class SubscriptionBase(BaseModel):
    name: str
    url: str
    expires_at: date
    brand: str | None = None

class SubscriptionCreate(SubscriptionBase):
    pass

class Subscription(SubscriptionBase):
    id: int

    class Config:
        from_attributes = True