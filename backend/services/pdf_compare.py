"""
Vizuální porovnání dvou PDF (originál vs. výstup po úpravě).

Smysl: zachytit tichou ztrátu obsahu (chybějící obrázek, prázdná nebo useknutá strana).
Strany se vykreslí v nízkém rozlišení (šedě) a porovnají se po pixelech i po blocích.
Je to hrubá pojistka — nezachytí jemné rozdíly (vlasová linka, mírně jiný odstín).
"""
from __future__ import annotations

import fitz  # PyMuPDF
from PIL import Image, ImageChops

_DPI = 50
_MAX_PIXELS = 600_000      # strop rastru jedné strany
_MAX_PAGES = 40            # u dlouhých dokumentů se porovná rovnoměrný vzorek stran
_PIXEL_TOL = 48            # rozdíl jasu (0–255), od kterého je pixel „odlišný"
_BLOCK = 16                # velikost bloku (px) pro lokální porovnání
_BLOCK_TOL = 24            # průměrný rozdíl jasu v bloku, od kterého je blok „výrazně odlišný"
#                            (kalibrace 16. 10. 2026: normální převod max. 18 i na husté stránce,
#                             chybějící řádek textu ~40, chybějící obrázek 100+)
_MAX_DIFF_FRACTION = 0.02  # podíl odlišných pixelů na straně
_MAX_DIFF_BLOCKS = 2       # počet výrazně odlišných bloků na straně


def _page_gray(page: fitz.Page, matrix: fitz.Matrix) -> Image.Image:
    pix = page.get_pixmap(matrix=matrix, colorspace=fitz.csGRAY, alpha=False)
    return Image.frombytes("L", (pix.width, pix.height), pix.samples)


def page_stats(src_page: fitz.Page, out_page: fitz.Page) -> tuple[float, int, int] | None:
    """(podíl odlišných pixelů, počet výrazně odlišných bloků, největší průměr bloku) nebo None."""
    area = src_page.rect.width * src_page.rect.height
    if area <= 0:
        return None
    scale = min(_DPI / 72, (_MAX_PIXELS / area) ** 0.5)
    matrix = fitz.Matrix(scale, scale)
    a = _page_gray(src_page, matrix)
    b = _page_gray(out_page, matrix)
    if a.size != b.size:
        return None
    diff = ImageChops.difference(a, b)
    total = diff.size[0] * diff.size[1]
    different = diff.point(lambda v: 255 if v > _PIXEL_TOL else 0).histogram()[255]
    blocks = diff.reduce(_BLOCK)
    hist = blocks.histogram()
    return different / total, sum(hist[_BLOCK_TOL + 1:]), blocks.getextrema()[1]


def compare_pdfs(src_path: str, out_path: str) -> tuple[str | None, list[str]]:
    """
    Vrátí (problém, poznámky). Problém = výstup se od originálu viditelně liší
    (typicky chybí obsah). Pokud nejde jedno z PDF vykreslit, srovnání se přeskočí
    s poznámkou (rozhodnutí o selhání nechává na volajícím).
    """
    notes: list[str] = []
    try:
        src = fitz.open(src_path)
        out = fitz.open(out_path)
    except Exception as exc:
        return None, [f"vizuální porovnání přeskočeno ({exc})"]

    if src.page_count != out.page_count:
        return f"počet stran se liší (originál {src.page_count}, výstup {out.page_count})", notes

    n = src.page_count
    if n > _MAX_PAGES:
        idx = sorted({round(i * (n - 1) / (_MAX_PAGES - 1)) for i in range(_MAX_PAGES)})
        notes.append(f"porovnáno {len(idx)} z {n} stran (vzorek)")
    else:
        idx = list(range(n))

    problems: list[str] = []
    for i in idx:
        try:
            stats = page_stats(src[i], out[i])
        except Exception as exc:
            notes.append(f"strana {i + 1}: porovnání přeskočeno ({exc})")
            continue
        if stats is None:
            notes.append(f"strana {i + 1}: porovnání přeskočeno (jiné rozměry)")
            continue
        fraction, blocks, _ = stats
        if fraction > _MAX_DIFF_FRACTION or blocks > _MAX_DIFF_BLOCKS:
            problems.append(
                f"strana {i + 1} se liší od originálu "
                f"({fraction * 100:.1f} % plochy, {blocks} výrazně odlišných oblastí)"
            )

    if problems:
        shown = "; ".join(problems[:3])
        more = f" (+{len(problems) - 3} dalších stran)" if len(problems) > 3 else ""
        return shown + more, notes
    return None, notes
