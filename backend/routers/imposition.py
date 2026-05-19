"""
Imposition endpoints — start, status, sheet preview.
"""
from __future__ import annotations

import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from models.job import Job, ImpositionConfig
from services.imposition_engine import (
    ImpositionRequest,
    ImpositionResult,
    run_imposition,
    sheet_format_dimensions,
    SHEET_FORMATS,
)

import fitz  # for sheet preview PNG

router = APIRouter(prefix="/api/jobs", tags=["imposition"])


# ---------------------------------------------------------------------------
# Request schema
# ---------------------------------------------------------------------------

class ImpositionRequestBody(BaseModel):
    imposition_type: str = "grid"           # grid / booklet_saddle / cut_stack
    sheet_format: str = "SRA3"              # A4 / A3 / SRA3 / SRA2 / B2 / custom
    sheet_width_mm: float = 320.0           # used only for custom
    sheet_height_mm: float = 450.0          # used only for custom
    rows: int = Field(default=2, ge=1, le=20)
    cols: int = Field(default=2, ge=1, le=20)
    gap_h_mm: float = Field(default=3.0, ge=0)
    gap_v_mm: float = Field(default=3.0, ge=0)
    margin_top_mm: float = Field(default=10.0, ge=0)
    margin_right_mm: float = Field(default=10.0, ge=0)
    margin_bottom_mm: float = Field(default=10.0, ge=0)
    margin_left_mm: float = Field(default=10.0, ge=0)
    scale: float = Field(default=1.0, gt=0, le=2.0)
    rotation: int = 0                       # 0 / 90 / 180 / 270
    marks_crop: bool = True
    marks_fold: bool = False
    marks_info: bool = True
    marks_registration: bool = True
    page_range: list[int] | None = None


# ---------------------------------------------------------------------------
# POST /api/jobs/{job_id}/impose  — run imposice synchronně
# ---------------------------------------------------------------------------

@router.post("/{job_id}/impose")
def start_imposition(
    job_id: str,
    body: ImpositionRequestBody,
    db: Session = Depends(get_db),
):
    job = _get_or_404(job_id, db)

    if not job.source_path or not Path(job.source_path).exists():
        raise HTTPException(status_code=404, detail="Zdrojový soubor nenalezen.")

    # Resolve sheet dimensions
    if body.sheet_format != "custom" and body.sheet_format in SHEET_FORMATS:
        w_mm, h_mm = SHEET_FORMATS[body.sheet_format]
    else:
        w_mm, h_mm = body.sheet_width_mm, body.sheet_height_mm

    if w_mm <= 0 or h_mm <= 0:
        raise HTTPException(status_code=400, detail="Neplatné rozměry archu.")

    output_dir = Path(settings.OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = str(output_dir / f"{job_id}_imposed.pdf")

    req = ImpositionRequest(
        source_path=job.source_path,
        output_path=output_path,
        job_id=job_id,
        imposition_type=body.imposition_type,
        sheet_format=body.sheet_format,
        sheet_width_mm=w_mm,
        sheet_height_mm=h_mm,
        rows=body.rows,
        cols=body.cols,
        gap_h_mm=body.gap_h_mm,
        gap_v_mm=body.gap_v_mm,
        margin_top_mm=body.margin_top_mm,
        margin_right_mm=body.margin_right_mm,
        margin_bottom_mm=body.margin_bottom_mm,
        margin_left_mm=body.margin_left_mm,
        scale=body.scale,
        rotation=body.rotation,
        marks_crop=body.marks_crop,
        marks_fold=body.marks_fold,
        marks_info=body.marks_info,
        marks_registration=body.marks_registration,
        page_range=body.page_range,
    )

    # Update job status
    job.status = "processing"
    db.commit()

    t0 = time.perf_counter()
    try:
        result: ImpositionResult = run_imposition(req)
    except Exception as exc:
        job.status = "error"
        job.notes = f"Imposice selhala: {exc}"
        db.commit()
        raise HTTPException(status_code=500, detail=f"Imposice selhala: {exc}")

    elapsed_ms = int((time.perf_counter() - t0) * 1000)

    # Persist config
    existing = db.query(ImpositionConfig).filter(ImpositionConfig.job_id == job_id).first()
    if existing:
        db.delete(existing)
        db.flush()

    cfg = ImpositionConfig(
        job_id=job_id,
        imposition_type=body.imposition_type,
        sheet_format=body.sheet_format,
        sheet_width_mm=w_mm,
        sheet_height_mm=h_mm,
        rows=body.rows,
        cols=body.cols,
        gap_h_mm=body.gap_h_mm,
        gap_v_mm=body.gap_v_mm,
        margin_top_mm=body.margin_top_mm,
        margin_right_mm=body.margin_right_mm,
        margin_bottom_mm=body.margin_bottom_mm,
        margin_left_mm=body.margin_left_mm,
        scale=body.scale,
        rotation=body.rotation,
        marks_crop=body.marks_crop,
        marks_fold=body.marks_fold,
        marks_info=body.marks_info,
        marks_registration=body.marks_registration,
        output_path=output_path,
    )
    db.add(cfg)

    job.status = "done"
    job.processing_time_ms = elapsed_ms
    job.processed_on = "rpi"
    db.commit()

    # Invalidate sheet preview cache
    preview_path = output_dir / f"{job_id}_imposed_preview.png"
    preview_path.unlink(missing_ok=True)

    return {
        "status": "done",
        "job_id": job_id,
        "output_path": output_path,
        "sheet_count": result.sheet_count,
        "pages_per_sheet": result.pages_per_sheet,
        "total_pages_imposed": result.total_pages_imposed,
        "sheet_width_mm": result.sheet_width_mm,
        "sheet_height_mm": result.sheet_height_mm,
        "processing_time_ms": elapsed_ms,
        "warnings": result.warnings,
    }


# ---------------------------------------------------------------------------
# GET /api/jobs/{job_id}/impose  — stav / config
# ---------------------------------------------------------------------------

@router.get("/{job_id}/impose")
def get_imposition(job_id: str, db: Session = Depends(get_db)):
    _get_or_404(job_id, db)
    cfg = db.query(ImpositionConfig).filter(ImpositionConfig.job_id == job_id).first()
    if not cfg:
        return {"status": "not_run", "job_id": job_id}
    output_exists = cfg.output_path and Path(cfg.output_path).exists()
    return {
        "status": "done" if output_exists else "output_missing",
        "job_id": job_id,
        "config": _cfg_to_dict(cfg),
    }


# ---------------------------------------------------------------------------
# GET /api/jobs/{job_id}/impose/preview  — PNG náhled 1. archu
# ---------------------------------------------------------------------------

@router.get("/{job_id}/impose/preview")
def get_sheet_preview(job_id: str, db: Session = Depends(get_db)):
    _get_or_404(job_id, db)
    cfg = db.query(ImpositionConfig).filter(ImpositionConfig.job_id == job_id).first()
    if not cfg or not cfg.output_path or not Path(cfg.output_path).exists():
        raise HTTPException(status_code=404, detail="Výstupní soubor imposice nenalezen.")

    output_dir = Path(settings.OUTPUT_DIR)
    preview_path = output_dir / f"{job_id}_imposed_preview.png"

    if not preview_path.exists():
        try:
            doc = fitz.open(cfg.output_path)
            page = doc[0]
            mat = fitz.Matrix(150 / 72, 150 / 72)  # 150 DPI
            pix = page.get_pixmap(matrix=mat, alpha=False)
            pix.save(str(preview_path))
            doc.close()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Náhled archu selhal: {exc}")

    def iter_file():
        with open(preview_path, "rb") as f:
            while chunk := f.read(65536):
                yield chunk

    return StreamingResponse(iter_file(), media_type="image/png")


# ---------------------------------------------------------------------------
# GET /api/jobs/{job_id}/impose/download  — stáhnout imposed PDF
# ---------------------------------------------------------------------------

@router.get("/{job_id}/impose/download")
def download_imposed(job_id: str, db: Session = Depends(get_db)):
    job = _get_or_404(job_id, db)
    cfg = db.query(ImpositionConfig).filter(ImpositionConfig.job_id == job_id).first()
    if not cfg or not cfg.output_path or not Path(cfg.output_path).exists():
        raise HTTPException(status_code=404, detail="Výstupní soubor imposice nenalezen.")

    def iter_file():
        with open(cfg.output_path, "rb") as f:
            while chunk := f.read(65536):
                yield chunk

    base = Path(job.source_filename or f"{job_id}.pdf").stem
    filename = f"{base}_imposed.pdf"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(iter_file(), media_type="application/pdf", headers=headers)


# ---------------------------------------------------------------------------
# GET /api/imposition/formats  — seznam formátů archů
# ---------------------------------------------------------------------------

@router.get("/imposition/formats", tags=["imposition"])
def list_sheet_formats():
    return [
        {"name": k, "width_mm": v[0], "height_mm": v[1]}
        for k, v in SHEET_FORMATS.items()
        if k != "custom"
    ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_or_404(job_id: str, db: Session) -> Job:
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} nenalezen.")
    return job


def _cfg_to_dict(cfg: ImpositionConfig) -> dict:
    return {
        "id": cfg.id,
        "job_id": cfg.job_id,
        "imposition_type": cfg.imposition_type,
        "sheet_format": cfg.sheet_format,
        "sheet_width_mm": cfg.sheet_width_mm,
        "sheet_height_mm": cfg.sheet_height_mm,
        "rows": cfg.rows,
        "cols": cfg.cols,
        "gap_h_mm": cfg.gap_h_mm,
        "gap_v_mm": cfg.gap_v_mm,
        "margin_top_mm": cfg.margin_top_mm,
        "margin_right_mm": cfg.margin_right_mm,
        "margin_bottom_mm": cfg.margin_bottom_mm,
        "margin_left_mm": cfg.margin_left_mm,
        "scale": cfg.scale,
        "rotation": cfg.rotation,
        "marks_crop": cfg.marks_crop,
        "marks_fold": cfg.marks_fold,
        "marks_info": cfg.marks_info,
        "marks_registration": cfg.marks_registration,
        "output_path": cfg.output_path,
    }
