"""
Imposition engine — grid, booklet (saddle-stitch), cut-stack.
PDF manipulation: pikepdf  |  Print marks: ReportLab overlaid via PyMuPDF
"""
from __future__ import annotations

import io
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import fitz  # PyMuPDF
import pikepdf
from reportlab.lib.colors import CMYKColor, black
from reportlab.pdfgen import canvas as rl_canvas

MM_TO_PT = 72.0 / 25.4
PT_TO_MM = 25.4 / 72.0


# ---------------------------------------------------------------------------
# Known sheet formats (width × height in mm, portrait orientation)
# ---------------------------------------------------------------------------
SHEET_FORMATS: dict[str, tuple[float, float]] = {
    "A4":    (210.0, 297.0),
    "A3":    (297.0, 420.0),
    "A2":    (420.0, 594.0),
    "SRA3":  (320.0, 450.0),
    "SRA2":  (450.0, 640.0),
    "B2":    (500.0, 707.0),
    "B1":    (707.0, 1000.0),
    "custom": (0.0, 0.0),  # caller must supply sheet_width_mm / sheet_height_mm
}


@dataclass
class ImpositionRequest:
    # Input
    source_path: str
    output_path: str
    job_id: str

    # Layout type
    imposition_type: Literal["grid", "booklet_saddle", "cut_stack"] = "grid"

    # Sheet
    sheet_format: str = "SRA3"
    sheet_width_mm: float = 320.0
    sheet_height_mm: float = 450.0

    # Grid / placement
    rows: int = 2
    cols: int = 2
    gap_h_mm: float = 3.0      # horizontal gap between columns
    gap_v_mm: float = 3.0      # vertical gap between rows
    margin_top_mm: float = 10.0
    margin_right_mm: float = 10.0
    margin_bottom_mm: float = 10.0
    margin_left_mm: float = 10.0

    # Page
    scale: float = 1.0
    rotation: int = 0          # 0 / 90 / 180 / 270

    # Print marks
    marks_crop: bool = True
    marks_fold: bool = False
    marks_info: bool = True
    marks_registration: bool = True

    # Pages to impose (1-based, None = all)
    page_range: list[int] | None = None

    def sheet_pt(self) -> tuple[float, float]:
        """Sheet size in points."""
        return (self.sheet_width_mm * MM_TO_PT, self.sheet_height_mm * MM_TO_PT)


@dataclass
class ImpositionResult:
    output_path: str
    sheet_count: int
    pages_per_sheet: int
    total_pages_imposed: int
    sheet_width_mm: float
    sheet_height_mm: float
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_imposition(request: ImpositionRequest) -> ImpositionResult:
    """Impose source PDF and write output.  Returns ImpositionResult."""
    Path(request.output_path).parent.mkdir(parents=True, exist_ok=True)

    if request.imposition_type == "grid":
        return _impose_grid(request)
    elif request.imposition_type == "booklet_saddle":
        return _impose_booklet_saddle(request)
    elif request.imposition_type == "cut_stack":
        return _impose_cut_stack(request)
    else:
        raise ValueError(f"Neznámý typ imposice: {request.imposition_type}")


# ---------------------------------------------------------------------------
# Grid imposice
# ---------------------------------------------------------------------------

def _impose_grid(req: ImpositionRequest) -> ImpositionResult:
    src = fitz.open(req.source_path)
    page_indices = _resolve_page_range(req.page_range, len(src))

    sheet_w_pt, sheet_h_pt = req.sheet_pt()
    pages_per_sheet = req.rows * req.cols

    # Available area after margins
    avail_w = sheet_w_pt - (req.margin_left_mm + req.margin_right_mm) * MM_TO_PT
    avail_h = sheet_h_pt - (req.margin_top_mm + req.margin_bottom_mm) * MM_TO_PT

    # Cell size (including gap)
    cell_w = (avail_w - (req.cols - 1) * req.gap_h_mm * MM_TO_PT) / req.cols
    cell_h = (avail_h - (req.rows - 1) * req.gap_v_mm * MM_TO_PT) / req.rows

    sheets_needed = math.ceil(len(page_indices) / pages_per_sheet)
    warnings: list[str] = []

    out_doc = fitz.open()

    for sheet_idx in range(sheets_needed):
        sheet_page = out_doc.new_page(width=sheet_w_pt, height=sheet_h_pt)

        for slot in range(pages_per_sheet):
            pi = sheet_idx * pages_per_sheet + slot
            if pi >= len(page_indices):
                break
            src_page_idx = page_indices[pi]
            src_page = src[src_page_idx]

            row = slot // req.cols
            col = slot % req.cols

            # Top-left corner of this cell
            cell_x = req.margin_left_mm * MM_TO_PT + col * (cell_w + req.gap_h_mm * MM_TO_PT)
            cell_y = req.margin_top_mm * MM_TO_PT + row * (cell_h + req.gap_v_mm * MM_TO_PT)

            # Source page rect (after rotation)
            src_rect = src_page.rect
            if req.rotation in (90, 270):
                src_w, src_h = src_rect.height, src_rect.width
            else:
                src_w, src_h = src_rect.width, src_rect.height

            # Scale to fit cell, respecting req.scale
            fit_scale = min(cell_w / src_w, cell_h / src_h) * req.scale
            placed_w = src_w * fit_scale
            placed_h = src_h * fit_scale

            # Center in cell
            x0 = cell_x + (cell_w - placed_w) / 2
            y0 = cell_y + (cell_h - placed_h) / 2
            dest_rect = fitz.Rect(x0, y0, x0 + placed_w, y0 + placed_h)

            # Show source page
            rotation_arg = req.rotation if req.rotation else 0
            sheet_page.show_pdf_page(dest_rect, src, src_page_idx, rotate=rotation_arg)

            # Crop marks for this cell
            if req.marks_crop:
                _draw_crop_marks(sheet_page, dest_rect, mark_len_pt=14, gap_pt=3)

        # Sheet info text
        if req.marks_info:
            _draw_info_text(
                sheet_page,
                text=f"{Path(req.source_path).name}  |  Arch {sheet_idx + 1}/{sheets_needed}",
                sheet_w=sheet_w_pt, sheet_h=sheet_h_pt,
            )

        # Registration marks
        if req.marks_registration:
            _draw_registration_marks(sheet_page, sheet_w_pt, sheet_h_pt)

    out_path = req.output_path
    out_doc.save(out_path, garbage=4, deflate=True)
    out_doc.close()
    src.close()

    return ImpositionResult(
        output_path=out_path,
        sheet_count=sheets_needed,
        pages_per_sheet=pages_per_sheet,
        total_pages_imposed=len(page_indices),
        sheet_width_mm=req.sheet_width_mm,
        sheet_height_mm=req.sheet_height_mm,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Booklet — saddle stitch
# ---------------------------------------------------------------------------

def _impose_booklet_saddle(req: ImpositionRequest) -> ImpositionResult:
    """2-up saddle stitch. Pages laid out: last, first | second, second-to-last, ..."""
    src = fitz.open(req.source_path)
    n = len(src)

    # Pad to multiple of 4
    padded = math.ceil(n / 4) * 4
    warnings: list[str] = []
    if padded != n:
        warnings.append(f"Počet stránek ({n}) byl doplněn prázdnými stránkami na {padded} (násobek 4).")

    sheet_w_pt, sheet_h_pt = req.sheet_pt()
    # Each half of the sheet = one page slot
    avail_w = (sheet_w_pt - (req.margin_left_mm + req.margin_right_mm) * MM_TO_PT) / 2
    avail_h = sheet_h_pt - (req.margin_top_mm + req.margin_bottom_mm) * MM_TO_PT
    margin_l = req.margin_left_mm * MM_TO_PT
    margin_t = req.margin_top_mm * MM_TO_PT

    # Build sheet sequence: pairs of (back-page, front-page) for each sheet
    order = _booklet_order(padded)
    sheet_count = len(order)

    out_doc = fitz.open()

    for sheet_idx, (left_pg, right_pg) in enumerate(order):
        sheet_page = out_doc.new_page(width=sheet_w_pt, height=sheet_h_pt)

        for side, src_pg_1based in enumerate([left_pg, right_pg]):
            src_pg = src_pg_1based - 1  # 0-based
            if src_pg < 0 or src_pg >= n:
                # Blank page slot
                continue

            page_obj = src[src_pg]
            src_rect = page_obj.rect
            fit_scale = min(avail_w / src_rect.width, avail_h / src_rect.height) * req.scale
            placed_w = src_rect.width * fit_scale
            placed_h = src_rect.height * fit_scale

            if side == 0:  # left
                x0 = margin_l + (avail_w - placed_w) / 2
            else:          # right
                x0 = margin_l + avail_w + req.gap_h_mm * MM_TO_PT + (avail_w - placed_w) / 2

            y0 = margin_t + (avail_h - placed_h) / 2
            dest_rect = fitz.Rect(x0, y0, x0 + placed_w, y0 + placed_h)
            sheet_page.show_pdf_page(dest_rect, src, src_pg)

            if req.marks_crop:
                _draw_crop_marks(sheet_page, dest_rect, mark_len_pt=14, gap_pt=3)

        # Fold mark — center vertical line indicator
        if req.marks_fold:
            mid_x = sheet_w_pt / 2
            _draw_fold_mark(sheet_page, mid_x, sheet_h_pt)

        if req.marks_info:
            _draw_info_text(
                sheet_page,
                text=f"{Path(req.source_path).name}  |  Arch {sheet_idx + 1}/{sheet_count}  (brožura)",
                sheet_w=sheet_w_pt, sheet_h=sheet_h_pt,
            )

        if req.marks_registration:
            _draw_registration_marks(sheet_page, sheet_w_pt, sheet_h_pt)

    out_path = req.output_path
    out_doc.save(out_path, garbage=4, deflate=True)
    out_doc.close()
    src.close()

    return ImpositionResult(
        output_path=out_path,
        sheet_count=sheet_count,
        pages_per_sheet=2,
        total_pages_imposed=n,
        sheet_width_mm=req.sheet_width_mm,
        sheet_height_mm=req.sheet_height_mm,
        warnings=warnings,
    )


def _booklet_order(n: int) -> list[tuple[int, int]]:
    """Return list of (left_page, right_page) 1-based for saddle-stitch."""
    sheets = n // 2
    order = []
    for i in range(sheets // 2):
        outer_l = n - i
        outer_r = i + 1
        inner_l = i + 2
        inner_r = n - i - 1
        order.append((outer_l, outer_r))
        if inner_l != inner_r:
            order.append((inner_l, inner_r))
        else:
            order.append((inner_l, inner_l))
    # Sort so sheet 1 = outside back/front
    return order


# ---------------------------------------------------------------------------
# Cut & stack
# ---------------------------------------------------------------------------

def _impose_cut_stack(req: ImpositionRequest) -> ImpositionResult:
    """
    Cut & stack: all N-up copies of one page on a sheet before moving on.
    Useful for business cards, stickers, etc.
    """
    src = fitz.open(req.source_path)
    page_indices = _resolve_page_range(req.page_range, len(src))

    sheet_w_pt, sheet_h_pt = req.sheet_pt()
    pages_per_sheet = req.rows * req.cols

    avail_w = sheet_w_pt - (req.margin_left_mm + req.margin_right_mm) * MM_TO_PT
    avail_h = sheet_h_pt - (req.margin_top_mm + req.margin_bottom_mm) * MM_TO_PT
    cell_w = (avail_w - (req.cols - 1) * req.gap_h_mm * MM_TO_PT) / req.cols
    cell_h = (avail_h - (req.rows - 1) * req.gap_v_mm * MM_TO_PT) / req.rows

    # For cut&stack we repeat each source page pages_per_sheet times, then next page
    warnings: list[str] = []
    out_doc = fitz.open()
    sheet_count = 0

    for src_page_idx in page_indices:
        src_page = src[src_page_idx]
        src_rect = src_page.rect
        if req.rotation in (90, 270):
            src_w, src_h = src_rect.height, src_rect.width
        else:
            src_w, src_h = src_rect.width, src_rect.height

        fit_scale = min(cell_w / src_w, cell_h / src_h) * req.scale
        placed_w = src_w * fit_scale
        placed_h = src_h * fit_scale

        # How many full sheets do we need to fill all slots?
        # (cut&stack = 1 sheet with N-up by default, but if pages_per_sheet is 1 it's 1:1)
        sheet_page = out_doc.new_page(width=sheet_w_pt, height=sheet_h_pt)
        sheet_count += 1

        for slot in range(pages_per_sheet):
            row = slot // req.cols
            col = slot % req.cols
            cell_x = req.margin_left_mm * MM_TO_PT + col * (cell_w + req.gap_h_mm * MM_TO_PT)
            cell_y = req.margin_top_mm * MM_TO_PT + row * (cell_h + req.gap_v_mm * MM_TO_PT)

            x0 = cell_x + (cell_w - placed_w) / 2
            y0 = cell_y + (cell_h - placed_h) / 2
            dest_rect = fitz.Rect(x0, y0, x0 + placed_w, y0 + placed_h)

            sheet_page.show_pdf_page(dest_rect, src, src_page_idx, rotate=req.rotation)

            if req.marks_crop:
                _draw_crop_marks(sheet_page, dest_rect, mark_len_pt=14, gap_pt=3)

        if req.marks_info:
            pg_num = page_indices.index(src_page_idx) + 1
            _draw_info_text(
                sheet_page,
                text=f"{Path(req.source_path).name}  |  Str. {pg_num}  (cut&stack {req.rows}×{req.cols})",
                sheet_w=sheet_w_pt, sheet_h=sheet_h_pt,
            )

        if req.marks_registration:
            _draw_registration_marks(sheet_page, sheet_w_pt, sheet_h_pt)

    out_path = req.output_path
    out_doc.save(out_path, garbage=4, deflate=True)
    out_doc.close()
    src.close()

    return ImpositionResult(
        output_path=out_path,
        sheet_count=sheet_count,
        pages_per_sheet=pages_per_sheet,
        total_pages_imposed=len(page_indices),
        sheet_width_mm=req.sheet_width_mm,
        sheet_height_mm=req.sheet_height_mm,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Print marks (drawn directly on fitz page via shape / text)
# ---------------------------------------------------------------------------

MARK_COLOR = (0.0, 0.0, 0.0)       # black in RGB space for fitz


def _draw_crop_marks(page: fitz.Page, rect: fitz.Rect, mark_len_pt: float = 14, gap_pt: float = 3):
    """Draw crop marks around a placed rectangle."""
    shape = page.new_shape()
    color = MARK_COLOR
    lw = 0.25

    x0, y0, x1, y1 = rect.x0, rect.y0, rect.x1, rect.y1

    # Top-left
    shape.draw_line(fitz.Point(x0 - gap_pt - mark_len_pt, y0), fitz.Point(x0 - gap_pt, y0))
    shape.draw_line(fitz.Point(x0, y0 - gap_pt - mark_len_pt), fitz.Point(x0, y0 - gap_pt))
    # Top-right
    shape.draw_line(fitz.Point(x1 + gap_pt, y0), fitz.Point(x1 + gap_pt + mark_len_pt, y0))
    shape.draw_line(fitz.Point(x1, y0 - gap_pt - mark_len_pt), fitz.Point(x1, y0 - gap_pt))
    # Bottom-left
    shape.draw_line(fitz.Point(x0 - gap_pt - mark_len_pt, y1), fitz.Point(x0 - gap_pt, y1))
    shape.draw_line(fitz.Point(x0, y1 + gap_pt), fitz.Point(x0, y1 + gap_pt + mark_len_pt))
    # Bottom-right
    shape.draw_line(fitz.Point(x1 + gap_pt, y1), fitz.Point(x1 + gap_pt + mark_len_pt, y1))
    shape.draw_line(fitz.Point(x1, y1 + gap_pt), fitz.Point(x1, y1 + gap_pt + mark_len_pt))

    shape.finish(color=color, width=lw)
    shape.commit()


def _draw_fold_mark(page: fitz.Page, x_center: float, sheet_h: float):
    """Dashed vertical center line for fold indication."""
    shape = page.new_shape()
    # Draw short dashes at top and bottom
    dash_len = 10
    gap = 5
    y = 0
    while y < sheet_h:
        y_end = min(y + dash_len, sheet_h)
        shape.draw_line(fitz.Point(x_center, y), fitz.Point(x_center, y_end))
        y += dash_len + gap
    shape.finish(color=MARK_COLOR, width=0.5)
    shape.commit()


def _draw_registration_marks(page: fitz.Page, sheet_w: float, sheet_h: float):
    """Draw CMY registration target circles at sheet edges."""
    positions = [
        (sheet_w / 2, 6),                   # top center
        (sheet_w / 2, sheet_h - 6),          # bottom center
        (6, sheet_h / 2),                    # left center
        (sheet_w - 6, sheet_h / 2),          # right center
    ]
    r = 4.0
    shape = page.new_shape()
    for cx, cy in positions:
        # Outer circle
        shape.draw_circle(fitz.Point(cx, cy), r)
        # Crosshair h
        shape.draw_line(fitz.Point(cx - r - 2, cy), fitz.Point(cx + r + 2, cy))
        # Crosshair v
        shape.draw_line(fitz.Point(cx, cy - r - 2), fitz.Point(cx, cy + r + 2))
    shape.finish(color=MARK_COLOR, width=0.5)
    shape.commit()


def _draw_info_text(page: fitz.Page, text: str, sheet_w: float, sheet_h: float):
    """Small info text at bottom of sheet outside printable area."""
    y = sheet_h - 3.5  # near bottom edge
    page.insert_text(
        fitz.Point(10, y),
        text,
        fontsize=5.5,
        color=MARK_COLOR,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_page_range(page_range: list[int] | None, total: int) -> list[int]:
    """Convert 1-based page range to 0-based indices, validate."""
    if not page_range:
        return list(range(total))
    result = []
    for p in page_range:
        idx = p - 1
        if 0 <= idx < total:
            result.append(idx)
    return result if result else list(range(total))


def sheet_format_dimensions(fmt: str, w_mm: float = 0, h_mm: float = 0) -> tuple[float, float]:
    """Return (width_mm, height_mm) for a named format or custom."""
    if fmt in SHEET_FORMATS and fmt != "custom":
        return SHEET_FORMATS[fmt]
    return (w_mm, h_mm)
