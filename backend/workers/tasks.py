"""
RQ worker tasks — each function runs in a separate worker process.
Each task creates its own SQLAlchemy session (workers are isolated processes).
"""
import asyncio
import time

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from config import settings

# Worker-local engine — separate from the FastAPI engine to avoid sharing state
_engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False},
)
_Session = sessionmaker(bind=_engine)


def task_run_preflight(job_id: str) -> None:
    """Run full preflight analysis for a job and persist the result."""
    db = _Session()
    try:
        from models.job import Job, PreflightResult

        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            return

        job.status = "processing"
        db.commit()

        start = time.time()

        from services.preflight_engine import run_full_preflight
        result_data = run_full_preflight(job.source_path)

        # Generate LLM report synchronously (asyncio.run is safe in worker context)
        from services.llm_reporter import generate_report
        llm_text = asyncio.run(generate_report(result_data))
        result_data["llm_report_cs"] = llm_text

        # Replace existing result if one already exists
        existing = db.query(PreflightResult).filter(
            PreflightResult.job_id == job_id
        ).first()
        if existing:
            db.delete(existing)
            db.flush()

        pr = PreflightResult(job_id=job_id, **result_data)
        db.add(pr)

        # Mark job done or needs_attention based on severity
        job.status = (
            "needs_attention" if pr.severity in ("warning", "error") else "done"
        )
        job.processing_time_ms = int((time.time() - start) * 1000)
        db.commit()

    except Exception as exc:
        db.rollback()
        # Try to mark the job as errored — best-effort
        try:
            from models.job import Job
            job2 = db.query(Job).filter(Job.id == job_id).first()
            if job2:
                job2.status = "error"
                job2.notes = str(exc)
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


def task_run_imposition(job_id: str, config: dict) -> None:
    """Stub: imposition task placeholder."""
    db = _Session()
    try:
        from models.job import Job
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            job.notes = "Imposice není zatím implementována."
            db.commit()
    finally:
        db.close()


def task_run_repair(job_id: str, actions: list[str]) -> None:
    """Stub: repair task placeholder."""
    db = _Session()
    try:
        from models.job import Job
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            job.notes = "Smart Repair není zatím implementován."
            db.commit()
    finally:
        db.close()
