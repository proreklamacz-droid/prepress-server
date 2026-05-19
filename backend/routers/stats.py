"""
Stats & cleanup endpoints.
GET  /api/jobs/stats    — počty jobů, velikosti souborů na disku
POST /api/jobs/cleanup  — smaž joby starší než N dní (default 30)
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from models.job import Job

router = APIRouter(prefix="/api/jobs", tags=["stats"])


# ---------------------------------------------------------------------------
# GET /api/jobs/stats
# ---------------------------------------------------------------------------

@router.get("/stats")
def get_stats(db: Session = Depends(get_db)):
    """Statistiky: počty jobů podle stavu, využití disku."""
    jobs = db.query(Job).all()

    # Status breakdown
    status_counts: dict[str, int] = {}
    for j in jobs:
        status_counts[j.status] = status_counts.get(j.status, 0) + 1

    # Disk usage
    upload_dir = Path(settings.UPLOAD_DIR)
    output_dir = Path(settings.OUTPUT_DIR)

    def dir_size(p: Path) -> int:
        if not p.exists():
            return 0
        return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())

    uploads_bytes = dir_size(upload_dir)
    outputs_bytes = dir_size(output_dir)

    # Oldest / newest job
    oldest = None
    newest = None
    if jobs:
        sorted_jobs = sorted(jobs, key=lambda j: j.created_at)
        oldest = sorted_jobs[0].created_at.isoformat()
        newest = sorted_jobs[-1].created_at.isoformat()

    return {
        "total_jobs": len(jobs),
        "status_counts": status_counts,
        "disk": {
            "uploads_bytes": uploads_bytes,
            "outputs_bytes": outputs_bytes,
            "total_bytes": uploads_bytes + outputs_bytes,
        },
        "oldest_job": oldest,
        "newest_job": newest,
    }


# ---------------------------------------------------------------------------
# POST /api/jobs/cleanup
# ---------------------------------------------------------------------------

@router.post("/cleanup")
def cleanup_jobs(
    older_than_days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db),
):
    """Smaž joby (a jejich soubory) starší než older_than_days dní."""
    cutoff = datetime.utcnow() - timedelta(days=older_than_days)
    old_jobs = db.query(Job).filter(Job.created_at < cutoff).all()

    deleted_jobs = 0
    freed_bytes = 0
    errors: list[str] = []

    output_dir = Path(settings.OUTPUT_DIR)

    for job in old_jobs:
        # Remove source file
        if job.source_path:
            p = Path(job.source_path)
            if p.exists():
                try:
                    freed_bytes += p.stat().st_size
                    p.unlink()
                except Exception as e:
                    errors.append(f"{job.id}: {e}")

        # Remove output files
        for pattern in [
            f"{job.id}_preview.png",
            f"{job.id}_imposed.pdf",
            f"{job.id}_imposed_preview.png",
            f"{job.id}_repaired.pdf",
        ]:
            p = output_dir / pattern
            if p.exists():
                try:
                    freed_bytes += p.stat().st_size
                    p.unlink()
                except Exception as e:
                    errors.append(f"{job.id}/{pattern}: {e}")

        db.delete(job)
        deleted_jobs += 1

    db.commit()

    return {
        "deleted_jobs": deleted_jobs,
        "freed_bytes": freed_bytes,
        "older_than_days": older_than_days,
        "cutoff": cutoff.isoformat(),
        "errors": errors,
    }
