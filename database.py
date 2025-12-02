# database.py — VERSI POSTGRESQL RENDER (Permanent & Reliable)

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# Ambil URL dari environment (Render otomatis inject)
SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL")

# Kalau URL diawali postgres:// (bukan postgresql://), Render butuh replace
if SQLALCHEMY_DATABASE_URL and SQLALCHEMY_DATABASE_URL.startswith("postgres://"):
    SQLALCHEMY_DATABASE_URL = SQLALCHEMY_DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=300,
    echo=False  # set True kalau mau liat SQL query di log
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()
