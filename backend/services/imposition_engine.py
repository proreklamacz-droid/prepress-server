"""
Imposition engine — grid, booklet (saddle-stitch), cut-stack.
PDF manipulation: PyMuPDF  |  Print marks: drawn via fitz shapes
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import fitz  # PyMuPDF

MM_TO_PT = 72.0 / 25.4
PT_TO_MM = 25.4 / 72.0

# ---------------------------------------------------------------------------
# Sheet formats
# ---------------------------------------------------------------------------
SHEET_FORMATS: dict[str, tuple[float, float]] = {
    "A4":    (210.0, 297.0),
    "A3":    (297.0, 420.0),
    "A2":    (420.0, 594.0),
    "SRA3":  (320.0, 450.0),
    "SRA2":  (450.0, 640.0),
    "B2":    (500.0, 707.0),
    "B1":    (707.0, 1000.0),
    "custom": (0.0, 0.0),
}

# ---------------------------------------------------------------------------
# Mark color helper
# ---------------------------------------------------------------------------

def _parse_color(color_str: str) -> tuple[float, float, float]:
    """
    Parse color string → (r, g, b) floats 0-1.
    Formats: 'black', 'white', '#rrggbb', 'r,g,b' (0-255 ints).
    """
    s = color_str.strip().lower()
    if s == "black":
        return (0.0, 0.0, 0.0)
    if s == "white":
        return (1.0, 1.0, 1.0)
    if s == "registration":
        return (0.0, 0.0, 0.0)  # fitz draws in device space; use black
    if s.startswith("#") and len(s) == 7:
        r = int(s[1:3], 16) / 255
        g = int(s[3:5], 16) / 255
        b = int(s[5:7], 16) / 255
        return (r, g, b)
    parts = s.split(",")
    if len(parts) == 3:
        return tuple(int(p.strip()) / 255 for p in parts)  # type: ignore
    return (0.0, 0.0, 0.0)


# ---------------------------------------------------------------------------
# Request / Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class CropMarkSettings:
    enabled: bool = True
    style: Literal["lines", "frame"] = "lines"  # lines = ořezové čárky, frame = rám
    length_mm: float = 5.0        # délka čárky
    offset_mm: float = 3.0        # odsazení od hrany stránky
    line_width_mm: float = 0.1    # tloušťka čáry
    color: str = "black"          # 'black', 'white', '#rrggbb', 'registration'


@dataclass
class ImpositionRequest:
    # Input
    source_path: str
    output_path: str
    job_id: str

    # Layout type
    imposition_type: Literal["grid", "booklet_saddle", "cut_stack", "step_repeat", "collage", "fill_sheet", "cut_stack_duplex"] = "grid"

    # Sheet
    sheet_format: str = "SRA3"
    sheet_width_mm: float = 320.0
    sheet_height_mm: float = 450.0

    # Grid / placement
    rows: int = 2
    cols: int = 2
    gap_h_mm: float = 0.0      # horizontal gap between columns
    gap_v_mm: float = 0.0      # vertical gap between rows
    margin_top_mm: float = 10.0
    margin_right_mm: float = 10.0
    margin_bottom_mm: float = 10.0
    margin_left_mm: float = 10.0

    # Layout alignment within available area
    # h_align: left / center / right
    # v_align: top / center / bottom
    h_align: Literal["left", "center", "right"] = "center"
    v_align: Literal["top", "center", "bottom"] = "center"

    # Page
    scale: float = 1.0           # 1.0 = fit to cell exactly; < 1.0 = shrink
    rotation: int = 0            # 0 / 90 / 180 / 270

    # Print marks
    crop_marks: CropMarkSettings = field(default_factory=CropMarkSettings)
    marks_fold: bool = False
    marks_info: bool = True
    marks_registration: bool = True

    # Pages to impose (1-based, None = all)
    page_range: list[int] | None = None

    # Auto-fit: ignoruje rows/cols, vypočítá optimální layout
    auto_fit: bool = False

    # Pro duplex (cut_stack_duplex): strana 2 PDF = zadní strana stránky 1
    # back_source_path: cesta k PDF se zadními stranami (None = druhá polovina stránek ze source)
    back_source_path: str | None = None

    def sheet_pt(self) -> tuple[float, float]:
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
    actual_scale: float = 1.0       # skutečné použité měřítko (může se lišit od požadovaného)
    actual_cols: int = 0            # skutečný počet sloupců
    actual_rows: int = 0            # skutečný počet řádků


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_imposition(request: ImpositionRequest) -> ImpositionResult:
    Path(request.output_path).parent.mkdir(parents=True, exist_ok=True)
    if request.imposition_type == "grid":
        return _impose_grid(request)
    elif request.imposition_type == "booklet_saddle":
        return _impose_booklet_saddle(request)
    elif request.imposition_type == "cut_stack":
        return _impose_cut_stack(request)
    elif request.imposition_type == "step_repeat":
        return _impose_step_repeat(request)
    elif request.imposition_type == "collage":
        return _impose_collage(request)
    elif request.imposition_type == "fill_sheet":
        return _impose_fill_sheet(request)
    elif request.imposition_type == "cut_stack_duplex":
        return _impose_cut_stack_duplex(request)
    else:
        raise ValueError(f"Neznámý typ imposice: {request.imposition_type}")


# ---------------------------------------------------------------------------
# Grid
# ---------------------------------------------------------------------------

def _impose_grid(req: ImpositionRequest) -> ImpositionResult:
    src = fitz.open(req.source_path)
    page_indices = _resolve_page_range(req.page_range, len(src))

    sheet_w_pt, sheet_h_pt = req.sheet_pt()
    pages_per_sheet = req.rows * req.cols

    # Available area inside margins
    margin_l = req.margin_left_mm * MM_TO_PT
    margin_t = req.margin_top_mm * MM_TO_PT
    avail_w = sheet_w_pt - (req.margin_left_mm + req.margin_right_mm) * MM_TO_PT
    avail_h = sheet_h_pt - (req.margin_top_mm + req.margin_bottom_mm) * MM_TO_PT
    gap_h_pt = req.gap_h_mm * MM_TO_PT
    gap_v_pt = req.gap_v_mm * MM_TO_PT

    # Determine page size from first source page (all pages assumed same size)
    first_src = src[page_indices[0]]
    src_rect0 = first_src.rect
    if req.rotation in (90, 270):
        page_w_pt = src_rect0.height * req.scale
        page_h_pt = src_rect0.width * req.scale
    else:
        page_w_pt = src_rect0.width * req.scale
        page_h_pt = src_rect0.height * req.scale

    warnings: list[str] = []

    # Dopočítej scale nebo rows/cols aby se NIKDY nepřekročily hranice archu
    scale_mode = "fit_grid" if req.auto_fit else "fit_scale"
    page_w_pt, page_h_pt, actual_scale, actual_cols, actual_rows = _resolve_grid_layout(
        src_rect0.width, src_rect0.height,
        req.cols, req.rows,
        avail_w, avail_h, gap_h_pt, gap_v_pt,
        req.scale, scale_mode, req.rotation,
    )
    pages_per_sheet = actual_cols * actual_rows

    if abs(actual_scale - req.scale) > 0.001:
        warnings.append(
            f"Měřítko upraveno na {actual_scale * 100:.1f} % "
            f"aby se {actual_cols}×{actual_rows} stránek vešlo na arch."
        )
    if scale_mode == "fit_grid" and (actual_cols != req.cols or actual_rows != req.rows):
        warnings.append(
            f"Rozložení upraveno na {actual_cols}×{actual_rows} "
            f"(zadáno {req.cols}×{req.rows}) pro měřítko {actual_scale * 100:.0f} %."
        )

    # Total block size
    block_w = actual_cols * page_w_pt + (actual_cols - 1) * gap_h_pt
    block_h = actual_rows * page_h_pt + (actual_rows - 1) * gap_v_pt

    # Align block within available area
    if req.h_align == "left":
        block_x = margin_l
    elif req.h_align == "right":
        block_x = margin_l + avail_w - block_w
    else:  # center
        block_x = margin_l + (avail_w - block_w) / 2

    if req.v_align == "top":
        block_y = margin_t
    elif req.v_align == "bottom":
        block_y = margin_t + avail_h - block_h
    else:  # center
        block_y = margin_t + (avail_h - block_h) / 2

    sheets_needed = math.ceil(len(page_indices) / pages_per_sheet)

    out_doc = fitz.open()

    for sheet_idx in range(sheets_needed):
        sheet_page = out_doc.new_page(width=sheet_w_pt, height=sheet_h_pt)

        for slot in range(pages_per_sheet):
            pi = sheet_idx * pages_per_sheet + slot
            if pi >= len(page_indices):
                break
            src_page_idx = page_indices[pi]

            row = slot // actual_cols
            col = slot % actual_cols

            x0 = block_x + col * (page_w_pt + gap_h_pt)
            y0 = block_y + row * (page_h_pt + gap_v_pt)
            dest_rect = fitz.Rect(x0, y0, x0 + page_w_pt, y0 + page_h_pt)

            sheet_page.show_pdf_page(dest_rect, src, src_page_idx,
                                     rotate=req.rotation if req.rotation else 0)

            _apply_marks(sheet_page, dest_rect, req.crop_marks)

        if req.marks_info:
            _draw_info_text(sheet_page,
                            f"{Path(req.source_path).name}  |  Arch {sheet_idx + 1}/{sheets_needed}",
                            sheet_w_pt, sheet_h_pt)
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
        actual_scale=actual_scale,
        actual_cols=actual_cols,
        actual_rows=actual_rows,
    )


# ---------------------------------------------------------------------------
# Booklet — saddle stitch
# ---------------------------------------------------------------------------

def _impose_booklet_saddle(req: ImpositionRequest) -> ImpositionResult:
    src = fitz.open(req.source_path)
    n = len(src)
    padded = math.ceil(n / 4) * 4
    warnings: list[str] = []
    if padded != n:
        warnings.append(f"Počet stránek ({n}) doplněn na {padded} (násobek 4).")

    sheet_w_pt, sheet_h_pt = req.sheet_pt()
    gap_h_pt = req.gap_h_mm * MM_TO_PT
    margin_l = req.margin_left_mm * MM_TO_PT
    margin_t = req.margin_top_mm * MM_TO_PT
    avail_w = sheet_w_pt - (req.margin_left_mm + req.margin_right_mm) * MM_TO_PT
    avail_h = sheet_h_pt - (req.margin_top_mm + req.margin_bottom_mm) * MM_TO_PT
    half_w = (avail_w - gap_h_pt) / 2

    order = _booklet_order(padded)
    sheet_count = len(order)
    out_doc = fitz.open()

    for sheet_idx, (left_pg, right_pg) in enumerate(order):
        sheet_page = out_doc.new_page(width=sheet_w_pt, height=sheet_h_pt)

        for side, src_pg_1based in enumerate([left_pg, right_pg]):
            src_pg = src_pg_1based - 1
            if src_pg < 0 or src_pg >= n:
                continue
            page_obj = src[src_pg]
            src_rect = page_obj.rect
            fit_scale = min(half_w / src_rect.width, avail_h / src_rect.height) * req.scale
            pw = src_rect.width * fit_scale
            ph = src_rect.height * fit_scale

            if side == 0:
                x0 = margin_l + (half_w - pw) / 2
            else:
                x0 = margin_l + half_w + gap_h_pt + (half_w - pw) / 2

            y0 = margin_t + (avail_h - ph) / 2
            dest_rect = fitz.Rect(x0, y0, x0 + pw, y0 + ph)
            sheet_page.show_pdf_page(dest_rect, src, src_pg)
            _apply_marks(sheet_page, dest_rect, req.crop_marks)

        if req.marks_fold:
            _draw_fold_mark(sheet_page, sheet_w_pt / 2, sheet_h_pt)
        if req.marks_info:
            _draw_info_text(sheet_page,
                            f"{Path(req.source_path).name}  |  Arch {sheet_idx + 1}/{sheet_count}  (brožura)",
                            sheet_w_pt, sheet_h_pt)
        if req.marks_registration:
            _draw_registration_marks(sheet_page, sheet_w_pt, sheet_h_pt)

    req.output_path
    out_doc.save(req.output_path, garbage=4, deflate=True)
    out_doc.close()
    src.close()

    return ImpositionResult(
        output_path=req.output_path,
        sheet_count=sheet_count,
        pages_per_sheet=2,
        total_pages_imposed=n,
        sheet_width_mm=req.sheet_width_mm,
        sheet_height_mm=req.sheet_height_mm,
        warnings=warnings,
    )


def _booklet_order(n: int) -> list[tuple[int, int]]:
    sheets = n // 2
    order = []
    for i in range(sheets // 2):
        order.append((n - i, i + 1))
        inner_l, inner_r = i + 2, n - i - 1
        if inner_l != inner_r:
            order.append((inner_l, inner_r))
        else:
            order.append((inner_l, inner_l))
    return order


# ---------------------------------------------------------------------------
# Cut & stack
# ---------------------------------------------------------------------------

def _impose_cut_stack(req: ImpositionRequest) -> ImpositionResult:
    src = fitz.open(req.source_path)
    page_indices = _resolve_page_range(req.page_range, len(src))

    sheet_w_pt, sheet_h_pt = req.sheet_pt()
    pages_per_sheet = req.rows * req.cols
    gap_h_pt = req.gap_h_mm * MM_TO_PT
    gap_v_pt = req.gap_v_mm * MM_TO_PT
    margin_l = req.margin_left_mm * MM_TO_PT
    margin_t = req.margin_top_mm * MM_TO_PT
    avail_w = sheet_w_pt - (req.margin_left_mm + req.margin_right_mm) * MM_TO_PT
    avail_h = sheet_h_pt - (req.margin_top_mm + req.margin_bottom_mm) * MM_TO_PT

    warnings: list[str] = []
    out_doc = fitz.open()
    sheet_count = 0
    actual_scale = req.scale
    actual_cols_final = req.cols
    actual_rows_final = req.rows

    for src_page_idx in page_indices:
        src_page = src[src_page_idx]
        src_rect = src_page.rect

        scale_mode = "fit_grid" if req.auto_fit else "fit_scale"
        page_w_pt, page_h_pt, actual_scale, actual_cols_cs, actual_rows_cs = _resolve_grid_layout(
            src_rect.width, src_rect.height,
            req.cols, req.rows,
            avail_w, avail_h, gap_h_pt, gap_v_pt,
            req.scale, scale_mode, req.rotation,
        )
        actual_cols_final = actual_cols_cs
        actual_rows_final = actual_rows_cs
        pages_per_sheet = actual_cols_cs * actual_rows_cs

        block_w = actual_cols_cs * page_w_pt + (actual_cols_cs - 1) * gap_h_pt
        block_h = actual_rows_cs * page_h_pt + (actual_rows_cs - 1) * gap_v_pt

        if req.h_align == "left":
            bx = margin_l
        elif req.h_align == "right":
            bx = margin_l + avail_w - block_w
        else:
            bx = margin_l + (avail_w - block_w) / 2

        if req.v_align == "top":
            by = margin_t
        elif req.v_align == "bottom":
            by = margin_t + avail_h - block_h
        else:
            by = margin_t + (avail_h - block_h) / 2

        sheet_page = out_doc.new_page(width=sheet_w_pt, height=sheet_h_pt)
        sheet_count += 1

        for slot in range(pages_per_sheet):
            row = slot // actual_cols_cs
            col = slot % actual_cols_cs
            x0 = bx + col * (page_w_pt + gap_h_pt)
            y0 = by + row * (page_h_pt + gap_v_pt)
            dest_rect = fitz.Rect(x0, y0, x0 + page_w_pt, y0 + page_h_pt)
            sheet_page.show_pdf_page(dest_rect, src, src_page_idx, rotate=req.rotation)
            _apply_marks(sheet_page, dest_rect, req.crop_marks)

        if req.marks_info:
            pg_num = page_indices.index(src_page_idx) + 1
            _draw_info_text(sheet_page,
                            f"{Path(req.source_path).name}  |  Str. {pg_num}  (cut&stack {req.rows}×{req.cols})",
                            sheet_w_pt, sheet_h_pt)
        if req.marks_registration:
            _draw_registration_marks(sheet_page, sheet_w_pt, sheet_h_pt)

    out_doc.save(req.output_path, garbage=4, deflate=True)
    out_doc.close()
    src.close()

    return ImpositionResult(
        output_path=req.output_path,
        sheet_count=sheet_count,
        pages_per_sheet=pages_per_sheet,
        total_pages_imposed=len(page_indices),
        sheet_width_mm=req.sheet_width_mm,
        sheet_height_mm=req.sheet_height_mm,
        warnings=warnings,
        actual_scale=actual_scale,
        actual_cols=actual_cols_final,
        actual_rows=actual_rows_final,
    )


# ---------------------------------------------------------------------------
# Helpers pro auto-fit
# ---------------------------------------------------------------------------

def _auto_fit_grid(
    page_w_pt: float, page_h_pt: float,
    avail_w: float, avail_h: float,
    gap_h_pt: float, gap_v_pt: float,
    try_rotate: bool = True,
) -> tuple[int, int, bool]:
    """
    Vypočítá optimální (cols, rows) aby se na arch vešlo co nejvíce kopií.
    Vrátí (cols, rows, rotated) — rotated=True pokud je lepší otočit stránku o 90°.
    """
    def fit(pw: float, ph: float) -> tuple[int, int]:
        cols = max(1, int((avail_w + gap_h_pt) / (pw + gap_h_pt)))
        rows = max(1, int((avail_h + gap_v_pt) / (ph + gap_v_pt)))
        return cols, rows

    cols0, rows0 = fit(page_w_pt, page_h_pt)
    count0 = cols0 * rows0

    if try_rotate and page_w_pt != page_h_pt:
        cols1, rows1 = fit(page_h_pt, page_w_pt)  # otočená
        count1 = cols1 * rows1
        if count1 > count0:
            return cols1, rows1, True

    return cols0, rows0, False


def _resolve_grid_layout(
    src_w_pt: float, src_h_pt: float,
    cols: int, rows: int,
    avail_w: float, avail_h: float,
    gap_h_pt: float, gap_v_pt: float,
    requested_scale: float,
    scale_mode: str,  # "fit_scale" = dopočítej scale z rows/cols, "fit_grid" = dopočítej rows/cols ze scale
    rotation: int,
) -> tuple[float, float, float, float, str]:
    """
    Vrátí (page_w_pt, page_h_pt, actual_scale, actual_cols, actual_rows, info_str).

    scale_mode="fit_scale":  rows/cols jsou pevné, scale se dopočítá tak aby se vše vešlo.
    scale_mode="fit_grid":   scale je pevný, rows/cols se dopočítají (kolik se vejde).

    Nikdy nepřekročí hranice archu.
    """
    if rotation in (90, 270):
        base_w, base_h = src_h_pt, src_w_pt
    else:
        base_w, base_h = src_w_pt, src_h_pt

    if scale_mode == "fit_scale":
        # Dopočítej max scale aby se cols×rows vešlo do avail
        max_scale_w = (avail_w - (cols - 1) * gap_h_pt) / (cols * base_w)
        max_scale_h = (avail_h - (rows - 1) * gap_v_pt) / (rows * base_h)
        actual_scale = min(max_scale_w, max_scale_h, requested_scale)
        actual_scale = max(actual_scale, 0.01)  # min 1 %
        actual_cols, actual_rows = cols, rows
    else:  # fit_grid
        actual_scale = requested_scale
        pw = base_w * actual_scale
        ph = base_h * actual_scale
        actual_cols = max(1, int((avail_w + gap_h_pt) / (pw + gap_h_pt)))
        actual_rows = max(1, int((avail_h + gap_v_pt) / (ph + gap_v_pt)))

    pw = base_w * actual_scale
    ph = base_h * actual_scale
    return pw, ph, actual_scale, actual_cols, actual_rows


def _place_grid_sheet(
    out_doc: fitz.Document,
    src: fitz.Document,
    slots: list[int],  # 0-based indexy stran pro tento arch
    page_w_pt: float, page_h_pt: float,
    cols: int,
    sheet_w_pt: float, sheet_h_pt: float,
    block_x: float, block_y: float,
    gap_h_pt: float, gap_v_pt: float,
    rotation: int,
    crop_marks: CropMarkSettings,
    info_text: str,
    marks_registration: bool,
) -> None:
    """Vloží jednu stránku archu s daným rozložením slotů."""
    sheet_page = out_doc.new_page(width=sheet_w_pt, height=sheet_h_pt)
    for slot_i, src_idx in enumerate(slots):
        row = slot_i // cols
        col = slot_i % cols
        x0 = block_x + col * (page_w_pt + gap_h_pt)
        y0 = block_y + row * (page_h_pt + gap_v_pt)
        dest_rect = fitz.Rect(x0, y0, x0 + page_w_pt, y0 + page_h_pt)
        sheet_page.show_pdf_page(dest_rect, src, src_idx, rotate=rotation)
        _apply_marks(sheet_page, dest_rect, crop_marks)
    if info_text:
        _draw_info_text(sheet_page, info_text, sheet_w_pt, sheet_h_pt)
    if marks_registration:
        _draw_registration_marks(sheet_page, sheet_w_pt, sheet_h_pt)


# ---------------------------------------------------------------------------
# Step & Repeat — jedna stránka, vyplní celý arch kopiemi
# ---------------------------------------------------------------------------

def _impose_step_repeat(req: ImpositionRequest) -> ImpositionResult:
    """
    Vezme první (nebo vybranou) stránku a zopakuje ji N-krát dokud nevyplní arch.
    Pokud má PDF více stran (a není zadán page_range), každá strana dostane vlastní arch.
    """
    src = fitz.open(req.source_path)
    page_indices = _resolve_page_range(req.page_range, len(src))

    sheet_w_pt, sheet_h_pt = req.sheet_pt()
    gap_h_pt = req.gap_h_mm * MM_TO_PT
    gap_v_pt = req.gap_v_mm * MM_TO_PT
    margin_l = req.margin_left_mm * MM_TO_PT
    margin_t = req.margin_top_mm * MM_TO_PT
    avail_w = sheet_w_pt - (req.margin_left_mm + req.margin_right_mm) * MM_TO_PT
    avail_h = sheet_h_pt - (req.margin_top_mm + req.margin_bottom_mm) * MM_TO_PT

    warnings: list[str] = []
    out_doc = fitz.open()
    sheet_count = 0

    for pi, src_idx in enumerate(page_indices):
        src_page = src[src_idx]
        src_rect = src_page.rect

        if req.rotation in (90, 270):
            base_w, base_h = src_rect.height, src_rect.width
        else:
            base_w, base_h = src_rect.width, src_rect.height

        # Auto-fit: zjisti optimální počet + případná rotace
        cols, rows, rotated = _auto_fit_grid(
            base_w * req.scale, base_h * req.scale,
            avail_w, avail_h, gap_h_pt, gap_v_pt,
        )
        actual_rot = (req.rotation + 90) % 360 if rotated else req.rotation
        if rotated:
            page_w_pt = base_h * req.scale
            page_h_pt = base_w * req.scale
        else:
            page_w_pt = base_w * req.scale
            page_h_pt = base_h * req.scale

        pages_per_sheet = cols * rows
        if pages_per_sheet == 0:
            warnings.append(f"Strana {pi+1}: stránka se nevejde na arch ani jednou.")
            continue

        block_w = cols * page_w_pt + (cols - 1) * gap_h_pt
        block_h = rows * page_h_pt + (rows - 1) * gap_v_pt
        bx = margin_l + (avail_w - block_w) / 2 if req.h_align == "center" else (
            margin_l if req.h_align == "left" else margin_l + avail_w - block_w)
        by = margin_t + (avail_h - block_h) / 2 if req.v_align == "center" else (
            margin_t if req.v_align == "top" else margin_t + avail_h - block_h)

        slots = [src_idx] * pages_per_sheet
        info = f"{Path(req.source_path).name}  |  Str. {pi+1}  ×{pages_per_sheet}  ({cols}×{rows})"
        _place_grid_sheet(
            out_doc, src, slots, page_w_pt, page_h_pt, cols,
            sheet_w_pt, sheet_h_pt, bx, by, gap_h_pt, gap_v_pt,
            actual_rot, req.crop_marks, info if req.marks_info else "",
            req.marks_registration,
        )
        sheet_count += 1
        if rotated:
            warnings.append(f"Strana {pi+1}: otočena o 90° pro lepší využití archu ({cols}×{rows} = {pages_per_sheet} ks).")

    out_doc.save(req.output_path, garbage=4, deflate=True)
    out_doc.close()
    src.close()

    return ImpositionResult(
        output_path=req.output_path,
        sheet_count=sheet_count,
        pages_per_sheet=sheet_count and (cols * rows) or 0,
        total_pages_imposed=len(page_indices),
        sheet_width_mm=req.sheet_width_mm,
        sheet_height_mm=req.sheet_height_mm,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Koláž — různé stránky, každá jednou, na jeden nebo více archů
# ---------------------------------------------------------------------------

def _impose_collage(req: ImpositionRequest) -> ImpositionResult:
    """
    Vyskládá všechny stránky PDF na co nejméně archů (každá strana jednou).
    Auto-fit podle první stránky (předpokládá stejně velké stránky).
    """
    src = fitz.open(req.source_path)
    page_indices = _resolve_page_range(req.page_range, len(src))

    sheet_w_pt, sheet_h_pt = req.sheet_pt()
    gap_h_pt = req.gap_h_mm * MM_TO_PT
    gap_v_pt = req.gap_v_mm * MM_TO_PT
    margin_l = req.margin_left_mm * MM_TO_PT
    margin_t = req.margin_top_mm * MM_TO_PT
    avail_w = sheet_w_pt - (req.margin_left_mm + req.margin_right_mm) * MM_TO_PT
    avail_h = sheet_h_pt - (req.margin_top_mm + req.margin_bottom_mm) * MM_TO_PT

    src_rect0 = src[page_indices[0]].rect
    if req.rotation in (90, 270):
        base_w, base_h = src_rect0.height, src_rect0.width
    else:
        base_w, base_h = src_rect0.width, src_rect0.height

    cols, rows, rotated = _auto_fit_grid(
        base_w * req.scale, base_h * req.scale,
        avail_w, avail_h, gap_h_pt, gap_v_pt,
    )
    actual_rot = (req.rotation + 90) % 360 if rotated else req.rotation
    if rotated:
        page_w_pt = base_h * req.scale
        page_h_pt = base_w * req.scale
    else:
        page_w_pt = base_w * req.scale
        page_h_pt = base_h * req.scale

    pages_per_sheet = cols * rows
    warnings: list[str] = []
    if rotated:
        warnings.append(f"Stránky otočeny o 90° pro lepší využití archu ({cols}×{rows} = {pages_per_sheet}/arch).")

    block_w = cols * page_w_pt + (cols - 1) * gap_h_pt
    block_h = rows * page_h_pt + (rows - 1) * gap_v_pt
    bx = margin_l + (avail_w - block_w) / 2 if req.h_align == "center" else (
        margin_l if req.h_align == "left" else margin_l + avail_w - block_w)
    by = margin_t + (avail_h - block_h) / 2 if req.v_align == "center" else (
        margin_t if req.v_align == "top" else margin_t + avail_h - block_h)

    out_doc = fitz.open()
    sheets_needed = math.ceil(len(page_indices) / pages_per_sheet)

    for sheet_idx in range(sheets_needed):
        start = sheet_idx * pages_per_sheet
        slots = page_indices[start : start + pages_per_sheet]
        info = f"{Path(req.source_path).name}  |  Arch {sheet_idx+1}/{sheets_needed}  (koláž)"
        _place_grid_sheet(
            out_doc, src, slots, page_w_pt, page_h_pt, cols,
            sheet_w_pt, sheet_h_pt, bx, by, gap_h_pt, gap_v_pt,
            actual_rot, req.crop_marks, info if req.marks_info else "",
            req.marks_registration,
        )

    out_doc.save(req.output_path, garbage=4, deflate=True)
    out_doc.close()
    src.close()

    return ImpositionResult(
        output_path=req.output_path,
        sheet_count=sheets_needed,
        pages_per_sheet=pages_per_sheet,
        total_pages_imposed=len(page_indices),
        sheet_width_mm=req.sheet_width_mm,
        sheet_height_mm=req.sheet_height_mm,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Fill Sheet — sada stran se opakuje dokud arch není plný
# ---------------------------------------------------------------------------

def _impose_fill_sheet(req: ImpositionRequest) -> ImpositionResult:
    """
    Opakuje celou sadu stran (např. 2 různé vizitky) dokud nevyplní arch.
    Výsledek: arch s max kopiemi, přičemž sada se opakuje v pořadí.
    """
    src = fitz.open(req.source_path)
    page_indices = _resolve_page_range(req.page_range, len(src))

    sheet_w_pt, sheet_h_pt = req.sheet_pt()
    gap_h_pt = req.gap_h_mm * MM_TO_PT
    gap_v_pt = req.gap_v_mm * MM_TO_PT
    margin_l = req.margin_left_mm * MM_TO_PT
    margin_t = req.margin_top_mm * MM_TO_PT
    avail_w = sheet_w_pt - (req.margin_left_mm + req.margin_right_mm) * MM_TO_PT
    avail_h = sheet_h_pt - (req.margin_top_mm + req.margin_bottom_mm) * MM_TO_PT

    src_rect0 = src[page_indices[0]].rect
    if req.rotation in (90, 270):
        base_w, base_h = src_rect0.height, src_rect0.width
    else:
        base_w, base_h = src_rect0.width, src_rect0.height

    cols, rows, rotated = _auto_fit_grid(
        base_w * req.scale, base_h * req.scale,
        avail_w, avail_h, gap_h_pt, gap_v_pt,
    )
    actual_rot = (req.rotation + 90) % 360 if rotated else req.rotation
    if rotated:
        page_w_pt = base_h * req.scale
        page_h_pt = base_w * req.scale
    else:
        page_w_pt = base_w * req.scale
        page_h_pt = base_h * req.scale

    pages_per_sheet = cols * rows
    warnings: list[str] = []
    if rotated:
        warnings.append(f"Stránky otočeny o 90° ({cols}×{rows} = {pages_per_sheet}/arch).")

    # Zaplní arch opakováním sady stran
    slots = []
    while len(slots) < pages_per_sheet:
        remaining = pages_per_sheet - len(slots)
        slots += page_indices[:remaining]

    block_w = cols * page_w_pt + (cols - 1) * gap_h_pt
    block_h = rows * page_h_pt + (rows - 1) * gap_v_pt
    bx = margin_l + (avail_w - block_w) / 2 if req.h_align == "center" else (
        margin_l if req.h_align == "left" else margin_l + avail_w - block_w)
    by = margin_t + (avail_h - block_h) / 2 if req.v_align == "center" else (
        margin_t if req.v_align == "top" else margin_t + avail_h - block_h)

    set_size = len(page_indices)
    repeats = math.ceil(pages_per_sheet / set_size)
    info = (f"{Path(req.source_path).name}  |  "
            f"Vyplnění archu  {pages_per_sheet}ks  ({set_size} vzorů ×{repeats})")

    out_doc = fitz.open()
    _place_grid_sheet(
        out_doc, src, slots, page_w_pt, page_h_pt, cols,
        sheet_w_pt, sheet_h_pt, bx, by, gap_h_pt, gap_v_pt,
        actual_rot, req.crop_marks, info if req.marks_info else "",
        req.marks_registration,
    )
    out_doc.save(req.output_path, garbage=4, deflate=True)
    out_doc.close()
    src.close()

    return ImpositionResult(
        output_path=req.output_path,
        sheet_count=1,
        pages_per_sheet=pages_per_sheet,
        total_pages_imposed=pages_per_sheet,
        sheet_width_mm=req.sheet_width_mm,
        sheet_height_mm=req.sheet_height_mm,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Cut & Stack Duplex — přední + zadní strana párovaně
# ---------------------------------------------------------------------------

def _impose_cut_stack_duplex(req: ImpositionRequest) -> ImpositionResult:
    """
    Duplex: přední arch (A) + zadní arch (B) tvoří pár pro oboustranný tisk.

    Logika:
    - Pokud back_source_path: přední = source, zadní = back_source
    - Jinak: předpokládá PDF se sudým počtem stran, první polovina = přední, druhá = zadní
      nebo střídání přední/zadní (strana 1=přední1, strana 2=zadní1, strana 3=přední2...)

    Každý pár stran dostane vlastní dvojarch (přední + zadní).
    """
    src_front = fitz.open(req.source_path)

    if req.back_source_path:
        src_back = fitz.open(req.back_source_path)
        front_indices = _resolve_page_range(req.page_range, len(src_front))
        back_indices = list(range(len(src_back)))
    else:
        # Střídání: liché stránky = přední, sudé = zadní
        all_indices = _resolve_page_range(req.page_range, len(src_front))
        front_indices = all_indices[0::2]   # 0, 2, 4...
        back_indices = all_indices[1::2]    # 1, 3, 5...
        src_back = src_front

    pairs = min(len(front_indices), len(back_indices))
    warnings: list[str] = []
    if len(front_indices) != len(back_indices):
        warnings.append(
            f"Počet předních ({len(front_indices)}) ≠ zadních ({len(back_indices)}) stran. "
            f"Zpracuji {pairs} párů."
        )

    sheet_w_pt, sheet_h_pt = req.sheet_pt()
    gap_h_pt = req.gap_h_mm * MM_TO_PT
    gap_v_pt = req.gap_v_mm * MM_TO_PT
    margin_l = req.margin_left_mm * MM_TO_PT
    margin_t = req.margin_top_mm * MM_TO_PT
    avail_w = sheet_w_pt - (req.margin_left_mm + req.margin_right_mm) * MM_TO_PT
    avail_h = sheet_h_pt - (req.margin_top_mm + req.margin_bottom_mm) * MM_TO_PT

    src_rect0 = src_front[front_indices[0]].rect
    if req.rotation in (90, 270):
        base_w, base_h = src_rect0.height, src_rect0.width
    else:
        base_w, base_h = src_rect0.width, src_rect0.height

    cols, rows, rotated = _auto_fit_grid(
        base_w * req.scale, base_h * req.scale,
        avail_w, avail_h, gap_h_pt, gap_v_pt,
    )
    actual_rot = (req.rotation + 90) % 360 if rotated else req.rotation
    if rotated:
        page_w_pt = base_h * req.scale
        page_h_pt = base_w * req.scale
    else:
        page_w_pt = base_w * req.scale
        page_h_pt = base_h * req.scale

    pages_per_sheet = cols * rows
    if rotated:
        warnings.append(f"Stránky otočeny o 90° ({cols}×{rows} = {pages_per_sheet}/arch).")

    block_w = cols * page_w_pt + (cols - 1) * gap_h_pt
    block_h = rows * page_h_pt + (rows - 1) * gap_v_pt
    bx = margin_l + (avail_w - block_w) / 2 if req.h_align == "center" else (
        margin_l if req.h_align == "left" else margin_l + avail_w - block_w)
    by = margin_t + (avail_h - block_h) / 2 if req.v_align == "center" else (
        margin_t if req.v_align == "top" else margin_t + avail_h - block_h)

    out_doc = fitz.open()
    sheet_count = 0
    pair_idx = 0

    while pair_idx < pairs:
        # Přední arch
        front_slots = front_indices[pair_idx : pair_idx + pages_per_sheet]
        # Doplň opakováním pokud méně než plný arch
        while len(front_slots) < pages_per_sheet:
            front_slots.append(front_slots[-1] if front_slots else front_indices[0])

        arch_num = sheet_count // 2 + 1
        total_arches = math.ceil(pairs / pages_per_sheet)

        _place_grid_sheet(
            out_doc, src_front, front_slots, page_w_pt, page_h_pt, cols,
            sheet_w_pt, sheet_h_pt, bx, by, gap_h_pt, gap_v_pt,
            actual_rot, req.crop_marks,
            f"{Path(req.source_path).name}  |  Arch {arch_num}/{total_arches}  PŘEDNÍ" if req.marks_info else "",
            req.marks_registration,
        )
        sheet_count += 1

        # Zadní arch (v cut&stack se tiskne v obráceném pořadí pro správné párování)
        back_slots = back_indices[pair_idx : pair_idx + pages_per_sheet]
        while len(back_slots) < pages_per_sheet:
            back_slots.append(back_slots[-1] if back_slots else back_indices[0])

        _place_grid_sheet(
            out_doc, src_back, back_slots, page_w_pt, page_h_pt, cols,
            sheet_w_pt, sheet_h_pt, bx, by, gap_h_pt, gap_v_pt,
            actual_rot, req.crop_marks,
            f"{Path(req.source_path).name}  |  Arch {arch_num}/{total_arches}  ZADNÍ" if req.marks_info else "",
            req.marks_registration,
        )
        sheet_count += 1
        pair_idx += pages_per_sheet

    out_doc.save(req.output_path, garbage=4, deflate=True)
    out_doc.close()
    src_front.close()
    if req.back_source_path:
        src_back.close()

    return ImpositionResult(
        output_path=req.output_path,
        sheet_count=sheet_count,
        pages_per_sheet=pages_per_sheet,
        total_pages_imposed=pairs,
        sheet_width_mm=req.sheet_width_mm,
        sheet_height_mm=req.sheet_height_mm,
        warnings=warnings,
    )

# ---------------------------------------------------------------------------
# Print marks dispatcher
# ---------------------------------------------------------------------------

def _apply_marks(page: fitz.Page, rect: fitz.Rect, settings: CropMarkSettings):
    if not settings.enabled:
        return
    color = _parse_color(settings.color)
    lw = max(settings.line_width_mm * MM_TO_PT, 0.1)
    if settings.style == "frame":
        _draw_frame(page, rect, color, lw)
    else:
        _draw_crop_marks(page, rect, color, lw,
                         settings.length_mm * MM_TO_PT,
                         settings.offset_mm * MM_TO_PT)


def _draw_crop_marks(page: fitz.Page, rect: fitz.Rect,
                     color: tuple, lw: float,
                     mark_len_pt: float, gap_pt: float):
    """Four corner crop mark lines."""
    shape = page.new_shape()
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


def _draw_frame(page: fitz.Page, rect: fitz.Rect,
                color: tuple, lw: float):
    """Rectangle frame around placed page."""
    shape = page.new_shape()
    shape.draw_rect(rect)
    shape.finish(color=color, fill=None, width=lw)
    shape.commit()


def _draw_fold_mark(page: fitz.Page, x_center: float, sheet_h: float):
    shape = page.new_shape()
    dash_len, gap = 10, 5
    y = 0.0
    while y < sheet_h:
        y_end = min(y + dash_len, sheet_h)
        shape.draw_line(fitz.Point(x_center, y), fitz.Point(x_center, y_end))
        y += dash_len + gap
    shape.finish(color=(0.0, 0.0, 0.0), width=0.5)
    shape.commit()


def _draw_registration_marks(page: fitz.Page, sheet_w: float, sheet_h: float):
    positions = [
        (sheet_w / 2, 6),
        (sheet_w / 2, sheet_h - 6),
        (6, sheet_h / 2),
        (sheet_w - 6, sheet_h / 2),
    ]
    r = 4.0
    shape = page.new_shape()
    for cx, cy in positions:
        shape.draw_circle(fitz.Point(cx, cy), r)
        shape.draw_line(fitz.Point(cx - r - 2, cy), fitz.Point(cx + r + 2, cy))
        shape.draw_line(fitz.Point(cx, cy - r - 2), fitz.Point(cx, cy + r + 2))
    shape.finish(color=(0.0, 0.0, 0.0), width=0.5)
    shape.commit()


def _draw_info_text(page: fitz.Page, text: str, sheet_w: float, sheet_h: float):
    page.insert_text(fitz.Point(10, sheet_h - 3.5), text, fontsize=5.5,
                     color=(0.0, 0.0, 0.0))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_page_range(page_range: list[int] | None, total: int) -> list[int]:
    if not page_range:
        return list(range(total))
    result = [p - 1 for p in page_range if 0 < p <= total]
    return result if result else list(range(total))


def sheet_format_dimensions(fmt: str, w_mm: float = 0, h_mm: float = 0) -> tuple[float, float]:
    if fmt in SHEET_FORMATS and fmt != "custom":
        return SHEET_FORMATS[fmt]
    return (w_mm, h_mm)
