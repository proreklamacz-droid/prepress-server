"""
Preflight endpoints: enqueue check (POST) and retrieve result (GET).
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models.job import Job, PreflightResult
from workers.queue import queue_normal
from workers.tasks import task_run_preflight

router = APIRouter(prefix="/api/jobs", tags=["preflight"])


@router.post("/{job_id}/preflight")
def start_preflight(job_id: str, db: Session = Depends(get_db)):
    """Enqueue preflight analysis. Returns immediately with queued status."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} nenalezen.")

    if job.status == "processing":
        raise HTTPException(status_code=409, detail="Job již probíhá.")

    # Reset to queued state before enqueuing
    job.status = "queued"
    job.notes = None
    db.commit()

    queue_normal.enqueue(task_run_preflight, job_id, job_timeout=300)

    return {"status": "queued", "job_id": job_id}


@router.get("/{job_id}/preflight")
def get_preflight(job_id: str, db: Session = Depends(get_db)):
    """Return the preflight result for a job, or 404 if not yet run."""
    result = db.query(PreflightResult).filter(PreflightResult.job_id == job_id).first()
    if not result:
        raise HTTPException(
            status_code=404, detail="Preflight výsledek zatím neexistuje."
        )

    return {
        "id": result.id,
        "job_id": result.job_id,
        "created_at": result.created_at.isoformat() if result.created_at else None,
        "fonts_ok": result.fonts_ok,
        "fonts_issues": result.fonts_issues,
        "resolution_ok": result.resolution_ok,
        "resolution_issues": result.resolution_issues,
        "resolution_min_dpi": result.resolution_min_dpi,
        "colorspace": result.colorspace,
        "colorspace_issues": result.colorspace_issues,
        "transparency_issues": result.transparency_issues,
        "overprint_issues": result.overprint_issues,
        "ink_coverage_max": result.ink_coverage_max,
        "ink_coverage_issues": result.ink_coverage_issues,
        "hairlines_found": result.hairlines_found,
        "hairlines_issues": result.hairlines_issues,
        "spot_colors": result.spot_colors,
        "layers_issues": result.layers_issues,
        "dtf_white_layer": result.dtf_white_layer,
        "dtf_transparent_bg": result.dtf_transparent_bg,
        "dtf_gamut_issues": result.dtf_gamut_issues,
        "llm_report_cs": result.llm_report_cs,
        "severity": result.severity,
    }
