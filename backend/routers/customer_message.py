"""Zpráva pro zákazníka: náhled a znovuvygenerování (nic se neodesílá)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models.job import Job, PreflightResult
from services import outbox
from services.customer_message import build_customer_message, data_from_result

router = APIRouter(prefix="/api/jobs", tags=["customer-message"])


@router.get("/{job_id}/customer-message")
def get_customer_message(job_id: str, db: Session = Depends(get_db)):
    if not db.query(Job).filter(Job.id == job_id).first():
        raise HTTPException(status_code=404, detail=f"Job {job_id} nenalezen.")
    message = outbox.read_message(job_id)
    if not message:
        raise HTTPException(status_code=404, detail="Zpráva pro zákazníka zatím neexistuje.")
    return message


@router.post("/{job_id}/customer-message")
def regenerate_customer_message(job_id: str, db: Session = Depends(get_db)):
    """Znovu složí zprávu z uloženého výsledku preflightu (nespouští preflight)."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} nenalezen.")
    pr = db.query(PreflightResult).filter(PreflightResult.job_id == job_id).first()
    if not pr:
        raise HTTPException(status_code=409, detail="Nejdřív spusťte preflight.")
    message = build_customer_message(job, data_from_result(pr))
    outbox.write_message(message)
    return outbox.read_message(job_id)
