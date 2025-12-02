# database.py — KONEKSI POSTGRESQL RENDER (PERMANENT & SUPER STABIL)

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# Ambil DATABASE_URL dari environment Render
SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL")

# Render kasih format postgres:// → harus diganti jadi postgresql+psycopg://
if SQLALCHEMY_DATABASE_URL and SQLALCHEMY_DATABASE_URL.startswith("postgres://"):
    SQLALCHEMY_DATABASE_URL = SQLALCHEMY_DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=300,
    echo=False  # ubah ke True kalau mau liat query SQL di log
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()
