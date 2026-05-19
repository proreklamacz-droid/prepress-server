import uuid
from datetime import datetime
from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey,
    Integer, JSON, String, UniqueConstraint,
)
from database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.utcnow()


class Job(Base):
    __tablename__ = "jobs"

    id = Column(String, primary_key=True, default=_uuid)
    created_at = Column(DateTime, default=_now, nullable=False)
    updated_at = Column(DateTime, default=_now, onupdate=_now, nullable=False)

    # Source file
    source_filename = Column(String, nullable=False)
    source_path = Column(String, nullable=False)
    source_size_bytes = Column(Integer, nullable=False)
    source_hash = Column(String(64), nullable=False)  # SHA256 hex

    # Client metadata (for future B2B/B2C portal)
    client_type = Column(String, nullable=False, default="internal")  # internal / b2b / b2c
    client_id = Column(String, nullable=True)

    # Processing state
    status = Column(String, nullable=False, default="queued")
    # queued / processing / done / error / needs_attention
    processed_on = Column(String, nullable=True)  # rpi / ai-core
    processing_time_ms = Column(Integer, nullable=True)
    notes = Column(String, nullable=True)

    # PDF metadata populated by pdf_analyzer on upload
    page_count = Column(Integer, nullable=True)
    pdf_version = Column(String, nullable=True)
    is_encrypted = Column(Boolean, nullable=False, default=False)
    page_dimensions = Column(JSON, nullable=True)
    # [{page, width_mm, height_mm, media_box, trim_box, bleed_box, crop_box}]


class PreflightResult(Base):
    __tablename__ = "preflight_results"
    __table_args__ = (UniqueConstraint("job_id"),)

    id = Column(String, primary_key=True, default=_uuid)
    job_id = Column(String, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, unique=True)
    created_at = Column(DateTime, default=_now, nullable=False)

    # Fonts
    fonts_ok = Column(Boolean, nullable=False, default=True)
    fonts_issues = Column(JSON, nullable=False, default=list)
    # [{name, page, issue_type}]

    # Resolution
    resolution_ok = Column(Boolean, nullable=False, default=True)
    resolution_issues = Column(JSON, nullable=False, default=list)
    # [{page, dpi, location}]
    resolution_min_dpi = Column(Integer, nullable=True)

    # Colorspace
    colorspace = Column(String, nullable=True)  # cmyk / rgb / mixed / unknown
    colorspace_issues = Column(JSON, nullable=False, default=list)

    # Transparency
    transparency_issues = Column(JSON, nullable=False, default=list)
    # [{page, type}]

    # Overprint
    overprint_issues = Column(JSON, nullable=False, default=list)

    # Ink coverage
    ink_coverage_max = Column(Float, nullable=True)  # percent, Xerox limit ~300%
    ink_coverage_issues = Column(JSON, nullable=False, default=list)

    # Hairlines (<0.25pt)
    hairlines_found = Column(Boolean, nullable=False, default=False)
    hairlines_issues = Column(JSON, nullable=False, default=list)

    # Spot colors
    spot_colors = Column(JSON, nullable=False, default=list)
    # [{name, page, converted}]

    # Layers
    layers_issues = Column(JSON, nullable=False, default=list)

    # DTF specifics
    dtf_white_layer = Column(Boolean, nullable=True)   # None = not checked
    dtf_transparent_bg = Column(Boolean, nullable=True)
    dtf_gamut_issues = Column(JSON, nullable=True)

    # LLM-generated human-readable report in Czech
    llm_report_cs = Column(String, nullable=True)

    # Overall severity
    severity = Column(String, nullable=False, default="ok")  # ok / warning / error


class ImpositionConfig(Base):
    __tablename__ = "imposition_configs"
    __table_args__ = (UniqueConstraint("job_id"),)

    id = Column(String, primary_key=True, default=_uuid)
    job_id = Column(String, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, unique=True)

    # Type
    imposition_type = Column(String, nullable=False)
    # grid / booklet_saddle / booklet_perfect / cut_stack

    # Sheet
    sheet_format = Column(String, nullable=False)  # SRA3 / A3 / B2 / custom
    sheet_width_mm = Column(Float, nullable=False)
    sheet_height_mm = Column(Float, nullable=False)

    # Grid layout
    rows = Column(Integer, nullable=False, default=1)
    cols = Column(Integer, nullable=False, default=1)
    gap_h_mm = Column(Float, nullable=False, default=0.0)
    gap_v_mm = Column(Float, nullable=False, default=0.0)
    margin_top_mm = Column(Float, nullable=False, default=0.0)
    margin_right_mm = Column(Float, nullable=False, default=0.0)
    margin_bottom_mm = Column(Float, nullable=False, default=0.0)
    margin_left_mm = Column(Float, nullable=False, default=0.0)

    # Page placement
    scale = Column(Float, nullable=False, default=1.0)
    rotation = Column(Integer, nullable=False, default=0)  # 0 / 90 / 180 / 270

    # Print marks
    marks_crop = Column(Boolean, nullable=False, default=True)
    marks_fold = Column(Boolean, nullable=False, default=False)
    marks_info = Column(Boolean, nullable=False, default=True)
    marks_registration = Column(Boolean, nullable=False, default=True)

    # Output
    output_path = Column(String, nullable=True)


class RepairLog(Base):
    __tablename__ = "repair_logs"

    id = Column(String, primary_key=True, default=_uuid)
    job_id = Column(String, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, default=_now, nullable=False)

    # What was done
    action = Column(String, nullable=False)
    # rgb_to_cmyk / flatten_transparency / add_bleed / dtf_add_white / ...
    description_cs = Column(String, nullable=False)

    # Optional before/after snapshot values
    before_value = Column(String, nullable=True)
    after_value = Column(String, nullable=True)

    success = Column(Boolean, nullable=False, default=True)
