from sqlalchemy import Column, Integer, String, Date, DateTime
from datetime import datetime
from database import Base

class Subscription(Base):
    __tablename__ = "subscription"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True, nullable=False)
    url = Column(String, nullable=False)
    expires_at = Column(Date, nullable=False)
    brand = Column(String, nullable=True)
    reminder_count_h3 = Column(Integer, default=0)
    reminder_count_h2 = Column(Integer, default=0)
    reminder_count_h1 = Column(Integer, default=0)
    reminder_count_h0 = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)