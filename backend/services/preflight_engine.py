"""
Preflight engine — checks PDF quality for print production.

Implemented:  fonts (PyMuPDF), resolution (PyMuPDF), colorspace (pikepdf)
Stubbed:      transparency, overprint, ink_coverage, hairlines, spot_colors,
              layers, dtf checks
"""
import fitz  # PyMuPDF
import pikepdf


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def check_fonts(pdf_path: str) -> tuple[bool, list[dict]]:
    """
    Detect non-embedded fonts.
    Returns (ok, issues) where issues = [{name, page, issue_type}].
    """
    doc = fitz.open(pdf_path)
    issues: list[dict] = []

    for page_num in range(len(doc)):
        page = doc[page_num]
        # full=True returns: (xref, ext, type, basefont, name, encoding, referencer)
        fonts = page.get_fonts(full=True)
        for font in fonts:
            xref, ext, font_type, basefont, name, encoding, referencer = font
            if xref == 0:  # xref == 0 means not embedded in the PDF
                issues.append({
                    "name": basefont or name or "unknown",
                    "page": page_num + 1,
                    "issue_type": "not_embedded",
                })

    return len(issues) == 0, issues


def check_resolution(
    pdf_path: str, min_dpi: int = 150
) -> tuple[bool, list[dict], int | None]:
    """
    Check that all raster images meet minimum DPI.
    Returns (ok, issues, min_dpi_found).
    """
    doc = fitz.open(pdf_path)
    issues: list[dict] = []
    min_found: int | None = None

    for page_num in range(len(doc)):
        page = doc[page_num]
        image_list = page.get_images(full=True)

        for img_info in image_list:
            xref = img_info[0]
            try:
                img = doc.extract_image(xref)
                w_px: int = img["width"]
                h_px: int = img["height"]

                rects = page.get_image_rects(xref)
                for rect in rects:
                    if rect.width <= 0 or rect.height <= 0:
                        continue
                    # rect dimensions are in PDF points (1 pt = 1/72 inch)
                    dpi_x = w_px / (rect.width / 72.0)
                    dpi_y = h_px / (rect.height / 72.0)
                    dpi = round(min(dpi_x, dpi_y))

                    if min_found is None or dpi < min_found:
                        min_found = dpi

                    if dpi < min_dpi:
                        issues.append({
                            "page": page_num + 1,
                            "dpi": dpi,
                            "location": str(rect),
                        })
            except Exception:
                # Skip images that can't be extracted (inline images, etc.)
                pass

    return len(issues) == 0, issues, min_found


def check_colorspace(pdf_path: str) -> tuple[str, list[dict]]:
    """
    Detect RGB vs CMYK colorspaces in XObject images.
    Returns (colorspace_str, issues).
    colorspace_str: "cmyk" | "rgb" | "mixed" | "unknown"
    """
    has_rgb = False
    has_cmyk = False
    issues: list[dict] = []

    with pikepdf.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages):
            resources = page.get("/Resources")
            if not resources:
                continue

            xobjects = resources.get("/XObject", {})
            for key in xobjects:
                try:
                    xobj = xobjects[key]
                    cs = xobj.get("/ColorSpace")
                    if not cs:
                        continue
                    cs_str = str(cs)
                    if any(x in cs_str for x in ["DeviceRGB", "CalRGB", "sRGB"]):
                        has_rgb = True
                        issues.append({
                            "page": page_num + 1,
                            "type": "rgb_image",
                            "object": str(key),
                        })
                    elif "DeviceCMYK" in cs_str:
                        has_cmyk = True
                except Exception:
                    pass

    if has_rgb and has_cmyk:
        return "mixed", issues
    if has_rgb:
        return "rgb", issues
    if has_cmyk:
        return "cmyk", []
    return "unknown", []


# ---------------------------------------------------------------------------
# Stubs — to be implemented in future iterations
# ---------------------------------------------------------------------------

def check_transparency(pdf_path: str) -> list[dict]:
    """Stub: detect transparent objects. Returns []."""
    return []


def check_overprint(pdf_path: str) -> list[dict]:
    """Stub: detect problematic overprint settings. Returns []."""
    return []


def check_ink_coverage(pdf_path: str) -> tuple[float | None, list[dict]]:
    """Stub: calculate TAC via Ghostscript. Returns (None, [])."""
    return None, []


def check_hairlines(pdf_path: str) -> tuple[bool, list[dict]]:
    """Stub: detect line widths < 0.25pt. Returns (False, [])."""
    return False, []


def check_spot_colors(pdf_path: str) -> list[dict]:
    """Stub: detect Pantone / custom spot colors. Returns []."""
    return []


def check_layers(pdf_path: str) -> list[dict]:
    """Stub: detect unflattened PDF layers (OCG). Returns []."""
    return []


# ---------------------------------------------------------------------------
# Severity logic
# ---------------------------------------------------------------------------

def _determine_severity(data: dict) -> str:
    """
    Decide overall severity based on collected preflight data.
    error   — critical issues (missing fonts, very low DPI)
    warning — non-critical issues (RGB colorspace, etc.)
    ok      — no issues
    """
    if not data["fonts_ok"]:
        return "error"
    if not data["resolution_ok"]:
        min_dpi = data.get("resolution_min_dpi")
        # Below 72 dpi is always an error; 72-149 is warning
        if min_dpi is not None and min_dpi < 72:
            return "error"
        return "warning"
    if data["colorspace"] in ("rgb", "mixed"):
        return "warning"
    return "ok"


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_full_preflight(pdf_path: str) -> dict:
    """
    Run all checks and return a dict ready to be unpacked into PreflightResult.
    LLM report is NOT generated here — done in the worker after this returns.
    """
    fonts_ok, fonts_issues = check_fonts(pdf_path)
    resolution_ok, resolution_issues, resolution_min_dpi = check_resolution(pdf_path)
    colorspace, colorspace_issues = check_colorspace(pdf_path)
    transparency_issues = check_transparency(pdf_path)
    overprint_issues = check_overprint(pdf_path)
    ink_coverage_max, ink_coverage_issues = check_ink_coverage(pdf_path)
    hairlines_found, hairlines_issues = check_hairlines(pdf_path)
    spot_colors = check_spot_colors(pdf_path)
    layers_issues = check_layers(pdf_path)

    data = {
        "fonts_ok": fonts_ok,
        "fonts_issues": fonts_issues,
        "resolution_ok": resolution_ok,
        "resolution_issues": resolution_issues,
        "resolution_min_dpi": resolution_min_dpi,
        "colorspace": colorspace,
        "colorspace_issues": colorspace_issues,
        "transparency_issues": transparency_issues,
        "overprint_issues": overprint_issues,
        "ink_coverage_max": ink_coverage_max,
        "ink_coverage_issues": ink_coverage_issues,
        "hairlines_found": hairlines_found,
        "hairlines_issues": hairlines_issues,
        "spot_colors": spot_colors,
        "layers_issues": layers_issues,
        "dtf_white_layer": None,
        "dtf_transparent_bg": None,
        "dtf_gamut_issues": None,
        "llm_report_cs": None,
        "severity": "",  # filled below
    }

    data["severity"] = _determine_severity(data)
    return data
