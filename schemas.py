from datetime import date
from pydantic import BaseModel

class SubscriptionCreate(BaseModel):
    name: str
    url: str
    expires_at: date
    brand: str | None = None

class Subscription(SubscriptionCreate):
    id: int

    class Config:
        from_attributes = True