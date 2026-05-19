"""
Analyzes a PDF on upload: extracts page count, dimensions (all boxes),
PDF version, encryption status and file size.
"""
import fitz  # PyMuPDF


def analyze_pdf(file_path: str) -> dict:
    """Return metadata dict that is merged into the Job record."""
    doc = fitz.open(file_path)
    dimensions: list[dict] = []

    for i, page in enumerate(doc):
        mb = page.mediabox
        # Only include optional boxes when they differ from mediabox
        tb = page.trimbox if page.trimbox != mb else None
        bb = page.bleedbox if page.bleedbox != mb else None
        cb = page.cropbox if page.cropbox != mb else None

        dimensions.append({
            "page": i + 1,
            "width_mm": round(mb.width * 25.4 / 72, 2),
            "height_mm": round(mb.height * 25.4 / 72, 2),
            "media_box": [round(x, 2) for x in [mb.x0, mb.y0, mb.x1, mb.y1]],
            "trim_box": [round(x, 2) for x in [tb.x0, tb.y0, tb.x1, tb.y1]] if tb else None,
            "bleed_box": [round(x, 2) for x in [bb.x0, bb.y0, bb.x1, bb.y1]] if bb else None,
            "crop_box": [round(x, 2) for x in [cb.x0, cb.y0, cb.x1, cb.y1]] if cb else None,
        })

    return {
        "page_count": len(doc),
        "pdf_version": str(doc.metadata.get("format", "unknown")),
        "is_encrypted": doc.is_encrypted,
        "page_dimensions": dimensions,
    }
