"""
PDF flattener — převede text na křivky (outlines) přes Ghostscript.

Proč: Canva a jiné online nástroje exportují PDF s nestandardně vloženými fonty
nebo subsetovanými fonty, které CorelDRAW, Illustrator a jiné aplikace nerozpoznají
a zobrazí je jako miniaturní obdélníky.

Řešení: Ghostscript s -dNoOutputFonts převede veškerý text na vektorové křivky
(Type 3 outlines). Výsledné PDF neobsahuje žádné závislosti na fontech.

Vedlejší efekt: PDF nelze editovat jako text, ale pro tisk je to standard.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


def flatten_text_to_curves(
    input_path: str,
    output_path: str,
    gs_path: str = "/usr/bin/gs",
) -> tuple[bool, str]:
    """
    Převede text v PDF na vektorové křivky přes Ghostscript.

    Returns:
        (success: bool, message: str)
    """
    input_p = Path(input_path)
    output_p = Path(output_path)

    if not input_p.exists():
        return False, f"Vstupní soubor neexistuje: {input_path}"

    # Ghostscript příkaz:
    # -dNoOutputFonts    ... text → Type3 křivky (nejspolehlivější)
    # -dBATCH -dNOPAUSE  ... dávkový režim bez interakce
    # -dSAFER            ... sandbox
    # -sDEVICE=pdfwrite  ... výstup PDF
    # -dCompatibilityLevel=1.4 ... kompatibilita
    # -dEmbedAllFonts=true ... fallback embedding
    cmd = [
        gs_path,
        "-dBATCH",
        "-dNOPAUSE",
        "-dSAFER",
        "-dQUIET",
        "-sDEVICE=pdfwrite",
        "-dCompatibilityLevel=1.4",
        "-dNoOutputFonts",          # ← text → křivky
        "-dEmbedAllFonts=true",
        "-dSubsetFonts=false",
        f"-sOutputFile={output_p}",
        str(input_p),
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,  # 2 minuty max
        )
        if result.returncode != 0:
            err = result.stderr.strip() or result.stdout.strip()
            logger.error(f"GS flatten failed: {err}")
            return False, f"Ghostscript selhal (kód {result.returncode}): {err[:200]}"

        if not output_p.exists() or output_p.stat().st_size < 100:
            return False, "Ghostscript nevygeneroval výstupní soubor."

        logger.info(
            f"Flatten OK: {input_p.name} "
            f"{input_p.stat().st_size // 1024} KB → "
            f"{output_p.stat().st_size // 1024} KB"
        )
        return True, "Text převeden na křivky."

    except subprocess.TimeoutExpired:
        return False, "Ghostscript překročil časový limit (120 s)."
    except FileNotFoundError:
        return False, f"Ghostscript nenalezen: {gs_path}"
    except Exception as exc:
        return False, f"Chyba při spuštění Ghostscriptu: {exc}"


def flatten_in_place(pdf_path: str, gs_path: str = "/usr/bin/gs") -> tuple[bool, str]:
    """
    Převede text na křivky přímo v souboru (přepíše originál).
    Bezpečně — nejprve zapíše do temp souboru, pak přepíše.
    """
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        ok, msg = flatten_text_to_curves(pdf_path, tmp_path, gs_path)
        if ok:
            shutil.move(tmp_path, pdf_path)
        else:
            Path(tmp_path).unlink(missing_ok=True)
        return ok, msg
    except Exception as exc:
        Path(tmp_path).unlink(missing_ok=True)
        return False, str(exc)


def ghostscript_available(gs_path: str = "/usr/bin/gs") -> bool:
    """Ověří že Ghostscript je dostupný."""
    try:
        r = subprocess.run([gs_path, "--version"], capture_output=True, timeout=5)
        return r.returncode == 0
    except Exception:
        return False
