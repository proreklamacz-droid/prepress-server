"""
Repair endpoints — stubs pending full implementation.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from models.job import RepairLog

router = APIRouter(prefix="/api/jobs", tags=["repair"])


@router.post("/{job_id}/repair")
def start_repair(job_id: str, db: Session = Depends(get_db)):
    return {"status": "not_implemented", "job_id": job_id}


@router.get("/{job_id}/repair")
def get_repair_logs(job_id: str, db: Session = Depends(get_db)):
    """Return all repair log entries for a job."""
    logs = (
        db.query(RepairLog)
        .filter(RepairLog.job_id == job_id)
        .order_by(RepairLog.created_at.asc())
        .all()
    )
    return [
        {
            "id": log.id,
            "job_id": log.job_id,
            "action": log.action,
            "description_cs": log.description_cs,
            "before_value": log.before_value,
            "after_value": log.after_value,
            "created_at": log.created_at.isoformat() if log.created_at else None,
            "success": log.success,
        }
        for log in logs
    ]
