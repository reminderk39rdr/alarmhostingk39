from datetime import date, datetime
from pydantic import BaseModel


class SubscriptionCreate(BaseModel):
    name: str
    url: str
    expires_at: date
    brand: str | None = None


class Subscription(SubscriptionCreate):
    id: int
    created_at: datetime | None = None
    is_archived: bool = False
    last_notified_at: datetime | None = None
    last_notified_stage: str | None = None

    class Config:
        from_attributes = True


class LogEntry(BaseModel):
    id: int
    level: str
    message: str
    created_at: datetime

    class Config:
        from_attributes = True
