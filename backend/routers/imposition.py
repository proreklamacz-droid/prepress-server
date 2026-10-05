"""
Imposition endpoints — start, status, sheet preview.
"""
from __future__ import annotations

import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from models.job import Job, ImpositionConfig
from services.imposition_engine import (
    CropMarkSettings,
    ImpositionRequest,
    ImpositionResult,
    run_imposition,
    SHEET_FORMATS,
)

import fitz

router = APIRouter(prefix="/api/jobs", tags=["imposition"])


# ---------------------------------------------------------------------------
# Request schema
# ---------------------------------------------------------------------------

class CropMarkBody(BaseModel):
    enabled: bool = True
    style: str = "lines"          # "lines" | "frame"
    length_mm: float = Field(default=5.0, ge=0.5, le=30.0)
    offset_mm: float = Field(default=3.0, ge=0.0, le=20.0)
    line_width_mm: float = Field(default=0.1, ge=0.05, le=1.0)
    color: str = "black"          # "black" | "white" | "#rrggbb"


class ImpositionRequestBody(BaseModel):
    imposition_type: str = "grid"
    sheet_format: str = "SRA3"
    sheet_width_mm: float = 320.0
    sheet_height_mm: float = 450.0
    rows: int = Field(default=2, ge=1, le=20)
    cols: int = Field(default=2, ge=1, le=20)
    gap_h_mm: float = Field(default=0.0, ge=0)
    gap_v_mm: float = Field(default=0.0, ge=0)
    margin_top_mm: float = Field(default=10.0, ge=0)
    margin_right_mm: float = Field(default=10.0, ge=0)
    margin_bottom_mm: float = Field(default=10.0, ge=0)
    margin_left_mm: float = Field(default=10.0, ge=0)
    h_align: str = "center"       # "left" | "center" | "right"
    v_align: str = "center"       # "top"  | "center" | "bottom"
    scale: float = Field(default=1.0, gt=0, le=2.0)
    rotation: int = 0
    crop_marks: CropMarkBody = Field(default_factory=CropMarkBody)
    marks_fold: bool = False
    marks_info: bool = True
    marks_registration: bool = True
    page_range: list[int] | None = None
    auto_fit: bool = True                  # automaticky vypočítá rows/cols
    back_job_id: str | None = None         # pro duplex: job_id PDF se zadními stranami


# ---------------------------------------------------------------------------
# POST /{job_id}/impose
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

    # Pokud existuje prepressovaná verze, použij ji jako vstup
    repaired_path = Path(settings.OUTPUT_DIR) / f"{job_id}_repaired.pdf"
    source_for_imposition = str(repaired_path) if repaired_path.exists() else job.source_path

    if body.sheet_format != "custom" and body.sheet_format in SHEET_FORMATS:
        w_mm, h_mm = SHEET_FORMATS[body.sheet_format]
    else:
        w_mm, h_mm = body.sheet_width_mm, body.sheet_height_mm

    if w_mm <= 0 or h_mm <= 0:
        raise HTTPException(status_code=400, detail="Neplatné rozměry archu.")

    output_dir = Path(settings.OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = str(output_dir / f"{job_id}_imposed.pdf")

    crop_settings = CropMarkSettings(
        enabled=body.crop_marks.enabled,
        style=body.crop_marks.style,
        length_mm=body.crop_marks.length_mm,
        offset_mm=body.crop_marks.offset_mm,
        line_width_mm=body.crop_marks.line_width_mm,
        color=body.crop_marks.color,
    )

    # Přeložit back_job_id na cestu ke zdrojovému souboru
    back_source = None
    if body.back_job_id:
        back_job = db.query(Job).filter(Job.id == body.back_job_id).first()
        if back_job and back_job.source_path and Path(back_job.source_path).exists():
            # Použij prepressed verzi pokud existuje
            back_repaired = Path(settings.OUTPUT_DIR) / f"{body.back_job_id}_repaired.pdf"
            back_source = str(back_repaired) if back_repaired.exists() else back_job.source_path

    req = ImpositionRequest(
        source_path=source_for_imposition,
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
        h_align=body.h_align,
        v_align=body.v_align,
        scale=body.scale,
        rotation=body.rotation,
        crop_marks=crop_settings,
        marks_fold=body.marks_fold,
        marks_info=body.marks_info,
        marks_registration=body.marks_registration,
        page_range=body.page_range,
        auto_fit=body.auto_fit,
        back_source_path=back_source,
    )

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
        marks_crop=body.crop_marks.enabled,
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
        "actual_scale_pct": round(result.actual_scale * 100, 1),
        "actual_cols": result.actual_cols,
        "actual_rows": result.actual_rows,
    }


# ---------------------------------------------------------------------------
# POST /{job_id}/impose/calculate — živý výpočet bez generování PDF
# ---------------------------------------------------------------------------

@router.post("/{job_id}/impose/calculate")
def calculate_imposition(
    job_id: str,
    body: ImpositionRequestBody,
    db: Session = Depends(get_db),
):
    """
    Vypočítá výsledné parametry imposice (skutečné měřítko, počet kopií atd.)
    bez generování výstupního PDF. Používá se pro živý feedback v UI.
    """
    import fitz as _fitz
    job = _get_or_404(job_id, db)

    if not job.source_path or not Path(job.source_path).exists():
        raise HTTPException(status_code=404, detail="Zdrojový soubor nenalezen.")

    if body.sheet_format != "custom" and body.sheet_format in SHEET_FORMATS:
        w_mm, h_mm = SHEET_FORMATS[body.sheet_format]
    else:
        w_mm, h_mm = body.sheet_width_mm, body.sheet_height_mm

    from services.imposition_engine import (
        MM_TO_PT, PT_TO_MM, _resolve_grid_layout, _auto_fit_grid
    )

    sheet_w_pt = w_mm * MM_TO_PT
    sheet_h_pt = h_mm * MM_TO_PT
    gap_h_pt = body.gap_h_mm * MM_TO_PT
    gap_v_pt = body.gap_v_mm * MM_TO_PT
    avail_w = sheet_w_pt - (body.margin_left_mm + body.margin_right_mm) * MM_TO_PT
    avail_h = sheet_h_pt - (body.margin_top_mm + body.margin_bottom_mm) * MM_TO_PT

    # Přečteme první stránku pro rozměry
    try:
        src = _fitz.open(job.source_path)
        src_rect = src[0].rect
        src.close()
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Nepodařilo se přečíst PDF: {exc}")

    scale_mode = "fit_grid" if body.auto_fit else "fit_scale"
    page_w_pt, page_h_pt, actual_scale, actual_cols, actual_rows = _resolve_grid_layout(
        src_rect.width, src_rect.height,
        body.cols, body.rows,
        avail_w, avail_h, gap_h_pt, gap_v_pt,
        body.scale, scale_mode, body.rotation,
    )

    pages_per_sheet = actual_cols * actual_rows
    block_w_mm = (actual_cols * page_w_pt + (actual_cols - 1) * gap_h_pt) * PT_TO_MM
    block_h_mm = (actual_rows * page_h_pt + (actual_rows - 1) * gap_v_pt) * PT_TO_MM
    page_w_mm = page_w_pt * PT_TO_MM
    page_h_mm = page_h_pt * PT_TO_MM

    utilization = (block_w_mm * block_h_mm) / (avail_w * PT_TO_MM * avail_h * PT_TO_MM) * 100

    warnings = []
    if abs(actual_scale - body.scale) > 0.001:
        warnings.append(
            f"Měřítko upraveno na {actual_scale * 100:.1f} % "
            f"aby se {actual_cols}×{actual_rows} stránek vešlo na arch."
        )

    return {
        "actual_scale_pct": round(actual_scale * 100, 1),
        "actual_cols": actual_cols,
        "actual_rows": actual_rows,
        "pages_per_sheet": pages_per_sheet,
        "page_size_mm": {"w": round(page_w_mm, 1), "h": round(page_h_mm, 1)},
        "block_size_mm": {"w": round(block_w_mm, 1), "h": round(block_h_mm, 1)},
        "avail_size_mm": {"w": round(avail_w * PT_TO_MM, 1), "h": round(avail_h * PT_TO_MM, 1)},
        "utilization_pct": round(utilization, 1),
        "fits": block_w_mm <= avail_w * PT_TO_MM and block_h_mm <= avail_h * PT_TO_MM,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# GET /{job_id}/impose
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
# GET /{job_id}/impose/preview
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
            mat = fitz.Matrix(150 / 72, 150 / 72)
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
# GET /{job_id}/impose/download
# ---------------------------------------------------------------------------

@router.get("/{job_id}/impose/download")
def download_imposed(job_id: str, db: Session = Depends(get_db)):
    job = _get_or_404(job_id, db)
    cfg = db.query(ImpositionConfig).filter(ImpositionConfig.job_id == job_id).first()
    if not cfg or not cfg.output_path or not Path(cfg.output_path).exists():
        raise HTTPException(status_code=404, detail="Výstupní soubor imposice nenalezen.")

    base = Path(job.source_filename or f"{job_id}.pdf").stem
    filename = f"{base}_imposed.pdf"
    return FileResponse(
        path=cfg.output_path,
        media_type="application/pdf",
        filename=filename,
    )


# ---------------------------------------------------------------------------
# GET /imposition/formats
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
