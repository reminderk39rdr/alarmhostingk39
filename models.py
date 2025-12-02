from sqlalchemy import Column, Integer, String, Date, DateTime
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class Subscription(Base):
    __tablename__ = "subscription"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    url = Column(String, nullable=False)
    expires_at = Column(Date, nullable=False)
    brand = Column(String, nullable=True)

    # Reminder counters
    reminder_count_h3 = Column(Integer, default=0)
    reminder_count_h2 = Column(Integer, default=0)
    reminder_count_h1 = Column(Integer, default=0)
    reminder_count_h0 = Column(Integer, default=0)

    last_reminder_time = Column(DateTime, nullable=True)
    last_reminder_type = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=True)