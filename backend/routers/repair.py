"""
Repair / Prepress endpoints.
POST /{job_id}/repair        — spustí prepress pipeline (text→křivky, RGB→CMYK, flatten)
GET  /{job_id}/repair        — vrátí logy oprav
POST /{job_id}/repair/download — stáhne opravené PDF
"""
from __future__ import annotations

import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from models.job import Job, RepairLog
from services.prepress_pipeline import (
    PrepressOptions,
    ghostscript_available,
    ghostscript_version,
    run_prepress_pipeline,
)

router = APIRouter(prefix="/api/jobs", tags=["repair"])


# ---------------------------------------------------------------------------
# Request schema
# ---------------------------------------------------------------------------

class RepairRequestBody(BaseModel):
    flatten_text: bool = True          # Text → křivky
    flatten_transparency: bool = True  # Průhlednosti → flatten
    convert_to_cmyk: bool = True       # RGB → CMYK
    cmyk_profile: str = "fogra39"      # fogra39 / fogra47 / default
    pdf_compatibility: str = "1.4"
    compress: bool = True


# ---------------------------------------------------------------------------
# POST /{job_id}/repair — spustí pipeline
# ---------------------------------------------------------------------------

@router.post("/{job_id}/repair")
def start_repair(
    job_id: str,
    body: RepairRequestBody = RepairRequestBody(),
    db: Session = Depends(get_db),
):
    job = _get_or_404(job_id, db)

    if not job.source_path or not Path(job.source_path).exists():
        raise HTTPException(status_code=404, detail="Zdrojový soubor nenalezen.")

    if not ghostscript_available(settings.GHOSTSCRIPT_PATH):
        raise HTTPException(
            status_code=503,
            detail="Ghostscript není dostupný. Kontaktuj administrátora.",
        )

    output_dir = Path(settings.OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = str(output_dir / f"{job_id}_repaired.pdf")

    opts = PrepressOptions(
        flatten_text=body.flatten_text,
        flatten_transparency=body.flatten_transparency,
        convert_to_cmyk=body.convert_to_cmyk,
        cmyk_profile=body.cmyk_profile,
        pdf_compatibility=body.pdf_compatibility,
        compress=body.compress,
    )

    job.status = "processing"
    db.commit()

    t0 = time.perf_counter()
    result = run_prepress_pipeline(
        job.source_path, output_path, opts, settings.GHOSTSCRIPT_PATH
    )
    elapsed_ms = int((time.perf_counter() - t0) * 1000)

    # Uložit logy do RepairLog
    step_labels = {
        "text_to_curves": "Text převeden na křivky",
        "embed_fonts": "Fonty vloženy (embed)",
        "flatten_transparency": "Průhlednosti zploštěny",
        "rgb_to_cmyk": "Barvy převedeny do CMYK",
        "icc_fogra39": "Aplikován ICC profil Fogra39",
        "icc_fogra47": "Aplikován ICC profil Fogra47",
        "compress": "PDF komprimováno a optimalizováno",
    }

    for step in result.steps_done:
        log = RepairLog(
            job_id=job_id,
            action=step,
            description_cs=step_labels.get(step, step),
            before_value=f"{result.size_before_kb} KB" if step == result.steps_done[0] else None,
            after_value=f"{result.size_after_kb} KB" if step == result.steps_done[-1] else None,
            success=result.success,
        )
        db.add(log)

    if result.warnings:
        for w in result.warnings:
            log = RepairLog(
                job_id=job_id,
                action="warning",
                description_cs=w[:500],
                success=True,
            )
            db.add(log)

    if result.success:
        job.status = "done"
        job.processing_time_ms = elapsed_ms
        job.processed_on = "rpi"
        # Invalidate preview cache
        (output_dir / f"{job_id}_preview.png").unlink(missing_ok=True)
    else:
        job.status = "error"
        job.notes = f"Prepress selhal: {result.error}"

    db.commit()

    if not result.success:
        raise HTTPException(
            status_code=500,
            detail=result.error or "Prepress pipeline selhala.",
        )

    return {
        "status": "done",
        "job_id": job_id,
        "steps_done": result.steps_done,
        "warnings": result.warnings,
        "size_before_kb": result.size_before_kb,
        "size_after_kb": result.size_after_kb,
        "processing_time_ms": elapsed_ms,
        "output_path": output_path,
        "gs_version": ghostscript_version(settings.GHOSTSCRIPT_PATH),
    }


# ---------------------------------------------------------------------------
# GET /{job_id}/repair — logy
# ---------------------------------------------------------------------------

@router.get("/{job_id}/repair")
def get_repair_logs(job_id: str, db: Session = Depends(get_db)):
    _get_or_404(job_id, db)
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


# ---------------------------------------------------------------------------
# GET /{job_id}/repair/download — stáhnout opravené PDF
# ---------------------------------------------------------------------------

@router.get("/{job_id}/repair/download")
def download_repaired(job_id: str, db: Session = Depends(get_db)):
    job = _get_or_404(job_id, db)
    output_path = Path(settings.OUTPUT_DIR) / f"{job_id}_repaired.pdf"
    if not output_path.exists():
        raise HTTPException(status_code=404, detail="Opravený soubor nenalezen. Spusť nejprve Prepress.")

    def iter_file():
        with open(output_path, "rb") as f:
            while chunk := f.read(65536):
                yield chunk

    base = Path(job.source_filename or f"{job_id}.pdf").stem
    headers = {"Content-Disposition": f'attachment; filename="{base}_prepress.pdf"'}
    return StreamingResponse(iter_file(), media_type="application/pdf", headers=headers)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_or_404(job_id: str, db: Session) -> Job:
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} nenalezen.")
    return job
