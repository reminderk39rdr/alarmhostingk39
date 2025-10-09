from .scheduler_logic import check_and_send_reminders
from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from contextlib import asynccontextmanager
import asyncio
from . import models, schemas, crud, database

# Buat tabel saat startup
@asynccontextmanager
async def lifespan(app: FastAPI):
    models.Base.metadata.create_all(bind=database.engine)
    yield

app = FastAPI(title="K39 Hosting Reminder", lifespan=lifespan)

def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- API Endpoints ---
@app.get("/subscriptions/", response_model=list[schemas.Subscription])
def read_subscriptions(db: Session = Depends(get_db)):
    return crud.get_subscriptions(db)

@app.post("/subscriptions/", response_model=schemas.Subscription)
def create_subscription(sub: schemas.SubscriptionCreate, db: Session = Depends(get_db)):
    return crud.create_subscription(db, sub)

@app.delete("/subscriptions/{sub_id}")
def delete_subscription(sub_id: int, db: Session = Depends(get_db)):
    if not crud.delete_subscription(db, sub_id):
        raise HTTPException(status_code=404, detail="Not found")
    return {"ok": True}

# --- Endpoint untuk cron eksternal ---
@app.get("/trigger")
async def trigger_reminders():
    db = database.SessionLocal()
    try:
        await check_and_send_reminders(db)
        return {"status": "Reminders sent", "time": str(datetime.now())}
    finally:
        db.close()

