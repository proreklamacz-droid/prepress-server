"""
PrePress Server — FastAPI entry point.
Tables are created at startup via SQLAlchemy lifespan event.
"""
from contextlib import asynccontextmanager
import logging

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database import engine, Base
# Import all models so their tables are registered with Base before create_all
import models  # noqa: F401

from routers import jobs, preflight, imposition, repair
from routers import stats as stats_router
from routers import presets as presets_router
from routers import technologies as technologies_router
from routers import customer_message as customer_message_router


# ---------------------------------------------------------------------------
# Auto cleanup job (APScheduler)
# ---------------------------------------------------------------------------

def _auto_cleanup():
    """Nightly: delete jobs older than 30 days."""
    from database import SessionLocal
    from models.job import Job
    from datetime import datetime, timedelta
    from pathlib import Path
    from config import settings as s
    from services import outbox
    from services.preview import cache_names

    cutoff = datetime.utcnow() - timedelta(days=30)
    db = SessionLocal()
    try:
        old = db.query(Job).filter(Job.created_at < cutoff).all()
        output_dir = Path(s.OUTPUT_DIR)
        for job in old:
            if job.source_path:
                Path(job.source_path).unlink(missing_ok=True)
            for pat in [
                f"{job.id}_preview.png",
                f"{job.id}_imposed.pdf",
                f"{job.id}_imposed_preview.png",
                f"{job.id}_repaired.pdf",
                f"{job.id}_original.pdf",
                *cache_names(job.id),
            ]:
                (output_dir / pat).unlink(missing_ok=True)
            outbox.delete_message(job.id)
            db.delete(job)
        db.commit()
        if old:
            logging.info(f"[auto_cleanup] Smazáno {len(old)} starých jobů.")
    finally:
        db.close()


_scheduler = BackgroundScheduler()
_scheduler.add_job(_auto_cleanup, "cron", hour=3, minute=0)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

def _migrate_sqlite() -> None:
    """create_all nepřidává sloupce do existujících tabulek — doplníme je ručně."""
    from sqlalchemy import inspect, text

    cols = {c["name"] for c in inspect(engine).get_columns("jobs")}
    if "technology" not in cols:
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE jobs ADD COLUMN technology VARCHAR NOT NULL DEFAULT 'default'"
            ))


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    _migrate_sqlite()
    _scheduler.start()
    yield
    _scheduler.shutdown(wait=False)


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="PrePress Server",
    description="PDF předtisková příprava — imposice, preflight, opravy",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(jobs.router)
app.include_router(preflight.router)
app.include_router(imposition.router)
app.include_router(repair.router)
app.include_router(stats_router.router)
app.include_router(presets_router.router)
app.include_router(technologies_router.router)
app.include_router(customer_message_router.router)


@app.get("/api/health", tags=["health"])
def health():
    return {"status": "ok"}
