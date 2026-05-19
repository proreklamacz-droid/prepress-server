"""
Job endpoints: upload, list, detail, delete, preview (PNG), download (PDF).
"""
import hashlib
import uuid
from pathlib import Path

import fitz  # PyMuPDF
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from models.job import Job, PreflightResult
from services.pdf_analyzer import analyze_pdf

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

@router.post("/upload")
def upload_job(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Receive a PDF, save it, run analysis, create Job record."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Pouze PDF soubory jsou povoleny.")

    # Read file into memory to check size and compute hash
    content = file.file.read()
    size_bytes = len(content)
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024

    if size_bytes > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Soubor je příliš velký. Maximum je {settings.MAX_UPLOAD_SIZE_MB} MB.",
        )

    file_hash = hashlib.sha256(content).hexdigest()
    job_id = str(uuid.uuid4())

    # Save file
    upload_dir = Path(settings.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest_path = upload_dir / f"{job_id}.pdf"
    dest_path.write_bytes(content)

    # Analyze PDF metadata
    try:
        pdf_meta = analyze_pdf(str(dest_path))
    except Exception as exc:
        dest_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=422,
            detail=f"Nepodařilo se analyzovat PDF: {exc}",
        )

    job = Job(
        id=job_id,
        source_filename=file.filename,
        source_path=str(dest_path),
        source_size_bytes=size_bytes,
        source_hash=file_hash,
        client_type="internal",
        status="queued",
        **pdf_meta,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    return _job_to_dict(job)


# ---------------------------------------------------------------------------
# List & detail
# ---------------------------------------------------------------------------

@router.get("")
def list_jobs(db: Session = Depends(get_db)):
    jobs = db.query(Job).order_by(Job.created_at.desc()).all()
    return [_job_to_dict(j) for j in jobs]


@router.get("/{job_id}")
def get_job(job_id: str, db: Session = Depends(get_db)):
    job = _get_or_404(job_id, db)
    result = db.query(PreflightResult).filter(PreflightResult.job_id == job_id).first()
    data = _job_to_dict(job)
    data["preflight"] = _preflight_to_dict(result) if result else None
    return data


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

@router.delete("/{job_id}")
def delete_job(job_id: str, db: Session = Depends(get_db)):
    job = _get_or_404(job_id, db)

    # Remove source file
    if job.source_path and Path(job.source_path).exists():
        Path(job.source_path).unlink(missing_ok=True)

    # Remove generated outputs (preview, processed PDF)
    output_dir = Path(settings.OUTPUT_DIR)
    for pattern in [f"{job_id}_preview.png", f"{job_id}_imposed.pdf", f"{job_id}_repaired.pdf"]:
        p = output_dir / pattern
        p.unlink(missing_ok=True)

    db.delete(job)
    db.commit()
    return {"deleted": True, "job_id": job_id}


# ---------------------------------------------------------------------------
# Preview (first page → PNG)
# ---------------------------------------------------------------------------

@router.get("/{job_id}/preview")
def get_preview(job_id: str, db: Session = Depends(get_db)):
    job = _get_or_404(job_id, db)

    output_dir = Path(settings.OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)
    preview_path = output_dir / f"{job_id}_preview.png"

    if not preview_path.exists():
        if not job.source_path or not Path(job.source_path).exists():
            raise HTTPException(status_code=404, detail="Zdrojový soubor nenalezen.")
        try:
            doc = fitz.open(job.source_path)
            page = doc[0]
            # 200 DPI: scale factor = 200/72 ≈ 2.78
            mat = fitz.Matrix(200 / 72, 200 / 72)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            pix.save(str(preview_path))
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Nepodařilo se vygenerovat náhled: {exc}",
            )

    def iter_file():
        with open(preview_path, "rb") as f:
            while chunk := f.read(65536):
                yield chunk

    return StreamingResponse(iter_file(), media_type="image/png")


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

@router.get("/{job_id}/download")
def download_job(job_id: str, db: Session = Depends(get_db)):
    """Download output PDF, or source PDF if no output exists yet."""
    job = _get_or_404(job_id, db)

    output_dir = Path(settings.OUTPUT_DIR)
    # Prefer repaired → imposed → source
    candidates = [
        output_dir / f"{job_id}_repaired.pdf",
        output_dir / f"{job_id}_imposed.pdf",
        Path(job.source_path) if job.source_path else None,
    ]

    target: Path | None = None
    for c in candidates:
        if c and c.exists():
            target = c
            break

    if not target:
        raise HTTPException(status_code=404, detail="Soubor nenalezen.")

    def iter_file():
        with open(target, "rb") as f:
            while chunk := f.read(65536):
                yield chunk

    filename = job.source_filename or f"{job_id}.pdf"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(iter_file(), media_type="application/pdf", headers=headers)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_or_404(job_id: str, db: Session) -> Job:
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} nenalezen.")
    return job


def _job_to_dict(job: Job) -> dict:
    return {
        "id": job.id,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
        "source_filename": job.source_filename,
        "source_size_bytes": job.source_size_bytes,
        "source_hash": job.source_hash,
        "client_type": job.client_type,
        "client_id": job.client_id,
        "status": job.status,
        "processed_on": job.processed_on,
        "processing_time_ms": job.processing_time_ms,
        "notes": job.notes,
        "page_count": job.page_count,
        "pdf_version": job.pdf_version,
        "is_encrypted": job.is_encrypted,
        "page_dimensions": job.page_dimensions,
    }


def _preflight_to_dict(r: PreflightResult) -> dict:
    return {
        "id": r.id,
        "job_id": r.job_id,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "fonts_ok": r.fonts_ok,
        "fonts_issues": r.fonts_issues,
        "resolution_ok": r.resolution_ok,
        "resolution_issues": r.resolution_issues,
        "resolution_min_dpi": r.resolution_min_dpi,
        "colorspace": r.colorspace,
        "colorspace_issues": r.colorspace_issues,
        "transparency_issues": r.transparency_issues,
        "overprint_issues": r.overprint_issues,
        "ink_coverage_max": r.ink_coverage_max,
        "ink_coverage_issues": r.ink_coverage_issues,
        "hairlines_found": r.hairlines_found,
        "hairlines_issues": r.hairlines_issues,
        "spot_colors": r.spot_colors,
        "layers_issues": r.layers_issues,
        "dtf_white_layer": r.dtf_white_layer,
        "dtf_transparent_bg": r.dtf_transparent_bg,
        "dtf_gamut_issues": r.dtf_gamut_issues,
        "llm_report_cs": r.llm_report_cs,
        "severity": r.severity,
    }
