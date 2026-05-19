"""
Imposition endpoints — stubs pending full implementation.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db

router = APIRouter(prefix="/api/jobs", tags=["imposition"])


@router.post("/{job_id}/impose")
def start_imposition(job_id: str, db: Session = Depends(get_db)):
    return {"status": "not_implemented", "job_id": job_id}


@router.get("/{job_id}/impose")
def get_imposition(job_id: str, db: Session = Depends(get_db)):
    return {"status": "not_implemented", "job_id": job_id}
