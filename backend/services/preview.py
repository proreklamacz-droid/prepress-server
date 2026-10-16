"""
Kontrolní náhledy první strany v různých režimech podkladu.

paper   — bílý papír (jako dřív)
checker — šachovnice (průhledná místa jsou vidět; bílá výplň zůstane bílá)
black   — černý podklad (např. černé tričko)
gray    — šedý podklad

Smysl: bílý obdélník v pozadí a skutečná průhlednost vypadají na bílém papíře stejně,
teprve na šachovnici nebo tmavém podkladu je rozdíl vidět (u DTF se bílá plocha vytiskne).
"""
from __future__ import annotations

import fitz  # PyMuPDF
from PIL import Image, ImageChops

PREVIEW_MODES = ("paper", "checker", "black", "gray")
_BG_COLORS = {"paper": (255, 255, 255), "black": (0, 0, 0), "gray": (128, 128, 128)}

_DEFAULT_DPI = 200
_MAX_PIXELS = 8_000_000  # strop rastru (velké formáty se zmenší)
_CHECK_SQUARE = 12       # velikost políčka šachovnice v px
_CHECK_LIGHT, _CHECK_DARK = 255, 204


def cache_names(job_id: str) -> list[str]:
    """Názvy cache souborů nových režimů (paper má původní `{job_id}_preview.png`)."""
    return [f"{job_id}_preview_{m}.png" for m in PREVIEW_MODES if m != "paper"]


def render_rgba(page: fitz.Page, scale: float) -> Image.Image:
    """Strana s průhledností jako RGBA. Pozor: MuPDF vrací barvy PŘEDEM VYNÁSOBENÉ alfou."""
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=True)
    return Image.frombytes("RGBA", (pix.width, pix.height), pix.samples)


def _checkerboard(size: tuple[int, int]) -> Image.Image:
    w, h = size
    tw, th = -(-w // _CHECK_SQUARE), -(-h // _CHECK_SQUARE)
    data = b"".join(
        bytes(_CHECK_LIGHT if (x + y) % 2 == 0 else _CHECK_DARK for x in range(tw))
        for y in range(th)
    )
    tiny = Image.frombytes("L", (tw, th), data)
    big = tiny.resize((tw * _CHECK_SQUARE, th * _CHECK_SQUARE), Image.NEAREST)
    return big.crop((0, 0, w, h)).convert("RGB")


def compose(premultiplied: Image.Image, mode: str) -> Image.Image:
    """Složí předem vynásobené RGBA na podklad: výsledek = barva + podklad × (1 − alfa)."""
    rgb = premultiplied.convert("RGB")
    if mode == "checker":
        background = _checkerboard(premultiplied.size)
    else:
        background = Image.new("RGB", premultiplied.size, _BG_COLORS[mode])
    inverse_alpha = ImageChops.invert(premultiplied.getchannel("A")).convert("RGB")
    return ImageChops.add(rgb, ImageChops.multiply(background, inverse_alpha))


def render_preview(
    pdf_path: str,
    out_path: str,
    mode: str = "checker",
    page_index: int = 0,
    dpi: int = _DEFAULT_DPI,
) -> None:
    if mode not in PREVIEW_MODES:
        raise ValueError(f"Neznámý režim náhledu: {mode}")
    doc = fitz.open(pdf_path)
    page = doc[page_index]
    area = page.rect.width * page.rect.height
    scale = min(dpi / 72, (_MAX_PIXELS / area) ** 0.5) if area > 0 else dpi / 72
    compose(render_rgba(page, scale), mode).save(out_path, "PNG")
