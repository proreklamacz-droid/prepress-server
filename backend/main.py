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
            ]:
                (output_dir / pat).unlink(missing_ok=True)
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

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
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


@app.get("/api/health", tags=["health"])
def health():
    return {"status": "ok"}
