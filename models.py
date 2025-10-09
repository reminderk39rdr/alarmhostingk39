# models.py
from sqlalchemy import Column, Integer, String, Date, DateTime
from database import Base
from datetime import datetime

class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    url = Column(String)
    expires_at = Column(Date)
    # Kolom baru untuk tracking reminder
    reminder_count_h3 = Column(Integer, default=0) # Jumlah reminder H-3
    reminder_count_h1 = Column(Integer, default=0) # Jumlah reminder H-1
    reminder_count_h0 = Column(Integer, default=0) # Jumlah reminder H-0
    last_reminder_time = Column(DateTime, default=None) # Waktu reminder terakhir dikirim
    last_reminder_type = Column(String, default=None) # Jenis reminder terakhir (h3, h1, h0)
    # Kolom baru untuk waktu penambahan
    created_at = Column(DateTime, default=datetime.now)
