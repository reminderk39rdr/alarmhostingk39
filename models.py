from sqlalchemy import Column, Integer, String, Date, DateTime, Boolean
from datetime import datetime
from database import Base


class Subscription(Base):
    __tablename__ = "subscription"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    url = Column(String, nullable=False)
    expires_at = Column(Date, nullable=False)
    brand = Column(String, nullable=True)

    reminder_count_h3 = Column(Integer, default=0)
    reminder_count_h2 = Column(Integer, default=0)
    reminder_count_h1 = Column(Integer, default=0)
    reminder_count_h0 = Column(Integer, default=0)

    created_at = Column(DateTime, default=datetime.utcnow)

    # NEW (safe migration)
    is_archived = Column(Boolean, default=False)
    last_notified_at = Column(DateTime, nullable=True)
    last_notified_stage = Column(String, nullable=True)  # "H-3","H-2","H-1/EXPIRED","DAILY"


class LogEntry(Base):
    __tablename__ = "log"

    id = Column(Integer, primary_key=True, index=True)
    level = Column(String, default="INFO")
    message = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
