from sqlalchemy import Column, Integer, String, Date, DateTime, Text
from datetime import datetime
from database import Base


class Subscription(Base):
    __tablename__ = "subscription"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    url = Column(String, nullable=False)
    expires_at = Column(Date, nullable=False)
    brand = Column(String, nullable=True)

    # reminder counters (existing)
    reminder_count_h3 = Column(Integer, default=0)
    reminder_count_h2 = Column(Integer, default=0)
    reminder_count_h1 = Column(Integer, default=0)
    reminder_count_h0 = Column(Integer, default=0)

    created_at = Column(DateTime, default=datetime.utcnow)


class LogEntry(Base):
    """
    Simpel log table buat ditampilin di dashboard.
    Ini gak ganggu tabel subscription.
    """
    __tablename__ = "log_entry"

    id = Column(Integer, primary_key=True, index=True)
    level = Column(String(20), default="INFO")  # INFO/WARN/ERROR
    message = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
