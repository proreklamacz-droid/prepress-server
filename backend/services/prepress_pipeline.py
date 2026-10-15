"""
Prepress pipeline — tiskový sanitizer.

Jeden průchod Ghostscriptem udělá vše potřebné pro tisk:
  1. Text → křivky (žádné závislosti na fontech)
  2. RGB → CMYK (Fogra39 nebo GrayGamma22 profil)
  3. Flatten průhledností
  4. Embed všech fontů (fallback)
  5. Komprese a optimalizace PDF

Výsledek je production-ready PDF připravené pro imposici a tisk.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# ICC profily — Ghostscript je má v sobě, nebo je hledáme na disku
_GS_ICC_DIRS = [
    "/app/data/icc",
    "/usr/share/ghostscript/icc",
    "/usr/share/ghostscript",
    "/usr/share/color/icc",
    "/usr/lib/ghostscript",
]

# Převzorkování fotek: zmenšíme jen to, co je nad cílovým rozlišením (bez zvětšování).
# Threshold 1.0 = zmenšit vše nad _TARGET_IMAGE_DPI (GS default je 1.5).
_TARGET_IMAGE_DPI = 300
_DOWNSAMPLE_THRESHOLD = 1.0

def _find_icc(filename: str) -> str | None:
    """Najde ICC profil na disku."""
    for d in _GS_ICC_DIRS:
        p = Path(d) / filename
        if p.exists():
            return str(p)
    return None


@dataclass
class PrepressOptions:
    """Konfigurace prepress pipeline."""

    # Text → křivky
    flatten_text: bool = True

    # Průhlednosti → flatten
    flatten_transparency: bool = True

    # Barevný prostor
    convert_to_cmyk: bool = True
    # "fogra39" = ISO Coated v2 (ofset), "fogra47" = Uncoated, "default" = GS default CMYK
    cmyk_profile: str = "fogra39"

    # PDF kompatibilita výstupu
    pdf_compatibility: str = "1.4"   # 1.3 = no transparency, 1.4 = standard, 1.5+ = layers

    # Komprese
    compress: bool = True

    # Zmenšit fotky nad 300 dpi na 300 dpi (nižší rozlišení se nemění)
    downsample_images: bool = True

    # Rozlišení pro rasterizaci (při flatten průhlednosti apod.)
    # 0 = GS default (zachovat vektorové prvky kde lze)
    resolution: int = 0


@dataclass
class PrepressResult:
    success: bool
    output_path: str
    steps_done: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
    size_before_kb: int = 0
    size_after_kb: int = 0


def run_prepress_pipeline(
    input_path: str,
    output_path: str,
    options: PrepressOptions | None = None,
    gs_path: str = "/usr/bin/gs",
) -> PrepressResult:
    """
    Spustí prepress pipeline na input_path, výsledek uloží do output_path.
    """
    if options is None:
        options = PrepressOptions()

    input_p = Path(input_path)
    output_p = Path(output_path)
    output_p.parent.mkdir(parents=True, exist_ok=True)

    if not input_p.exists():
        return PrepressResult(
            success=False,
            output_path=output_path,
            error=f"Vstupní soubor neexistuje: {input_path}",
        )

    size_before = input_p.stat().st_size // 1024
    steps_done: list[str] = []
    warnings: list[str] = []

    # --- Sestavení GS příkazu ---
    cmd = [
        gs_path,
        "-dBATCH",
        "-dNOPAUSE",
        "-dSAFER",
        "-dQUIET",
        "-sDEVICE=pdfwrite",
        f"-dCompatibilityLevel={options.pdf_compatibility}",
    ]

    # Text → křivky
    if options.flatten_text:
        cmd.append("-dNoOutputFonts")
        steps_done.append("text_to_curves")

    # Embed fontů (fallback — pokud flatten_text není zapnutý)
    if not options.flatten_text:
        cmd += ["-dEmbedAllFonts=true", "-dSubsetFonts=false"]
        steps_done.append("embed_fonts")

    # Flatten průhlednosti — PDF 1.3 nemá průhlednosti
    if options.flatten_transparency:
        if options.pdf_compatibility < "1.4":
            # Průhlednosti se automaticky flattenou při downgrade na 1.3
            pass
        else:
            # Vynutíme flatten explicitně
            cmd.append("-dFlattenTransparency=true")
        steps_done.append("flatten_transparency")

    # RGB → CMYK konverze
    if options.convert_to_cmyk:
        cmyk_cmd, cmyk_steps, cmyk_warns = _build_cmyk_args(options.cmyk_profile, gs_path)
        cmd += cmyk_cmd
        steps_done += cmyk_steps
        warnings += cmyk_warns

    # Komprese
    if options.compress:
        cmd += [
            "-dCompressFonts=true",
            "-dCompressPages=true",
            "-dOptimize=true",
        ]
        steps_done.append("compress")

    # Převzorkování fotek na tiskové rozlišení
    if options.downsample_images:
        for kind in ("Color", "Gray"):
            cmd += [
                f"-dDownsample{kind}Images=true",
                f"-d{kind}ImageDownsampleType=/Bicubic",
                f"-d{kind}ImageResolution={_TARGET_IMAGE_DPI}",
                f"-d{kind}ImageDownsampleThreshold={_DOWNSAMPLE_THRESHOLD}",
            ]
        steps_done.append(f"downsample_{_TARGET_IMAGE_DPI}dpi")

    # Rozlišení
    if options.resolution > 0:
        cmd += [f"-r{options.resolution}"]

    cmd += [f"-sOutputFile={output_p}", str(input_p)]

    # --- Spuštění ---
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,  # 5 minut max
        )

        err = (result.stderr or result.stdout or "").strip()

        # Nenulový kód = selhání. Částečný výstup nikdy nepoužijeme.
        if result.returncode != 0:
            output_p.unlink(missing_ok=True)
            return PrepressResult(
                success=False,
                output_path=output_path,
                steps_done=steps_done,
                warnings=warnings,
                error=f"Ghostscript selhal (kód {result.returncode}): {err[-300:]}",
                size_before_kb=size_before,
            )

        if not output_p.exists() or output_p.stat().st_size < 100:
            return PrepressResult(
                success=False,
                output_path=output_path,
                steps_done=steps_done,
                warnings=warnings,
                error="Ghostscript nevygeneroval výstupní soubor.",
                size_before_kb=size_before,
            )

        # GS hlásí chyby i s kódem 0 (typicky poškozený vstup) — to je selhání, ne varování
        gs_errors, gs_warnings = _gs_messages(err)
        warnings += gs_warnings
        if gs_errors:
            output_p.unlink(missing_ok=True)
            return PrepressResult(
                success=False,
                output_path=output_path,
                steps_done=steps_done,
                warnings=warnings,
                error="Ghostscript hlásí chybu (zdrojové PDF je pravděpodobně poškozené): "
                      + " | ".join(gs_errors),
                size_before_kb=size_before,
            )

        # Kontrola výstupu: otevře se, počet stran a rozměry sedí se vstupem
        problem, check_warnings = _validate_output(input_p, output_p)
        warnings += check_warnings
        if problem:
            output_p.unlink(missing_ok=True)
            return PrepressResult(
                success=False,
                output_path=output_path,
                steps_done=steps_done,
                warnings=warnings,
                error=f"Kontrola výstupu selhala: {problem}",
                size_before_kb=size_before,
            )

        size_after = output_p.stat().st_size // 1024
        logger.info(
            f"Prepress OK: {input_p.name} | "
            f"{size_before} KB → {size_after} KB | "
            f"kroky: {', '.join(steps_done)}"
        )

        return PrepressResult(
            success=True,
            output_path=str(output_p),
            steps_done=steps_done,
            warnings=warnings,
            size_before_kb=size_before,
            size_after_kb=size_after,
        )

    except subprocess.TimeoutExpired:
        return PrepressResult(
            success=False,
            output_path=output_path,
            steps_done=steps_done,
            error="Ghostscript překročil časový limit (300 s).",
            size_before_kb=size_before,
        )
    except FileNotFoundError:
        return PrepressResult(
            success=False,
            output_path=output_path,
            error=f"Ghostscript nenalezen: {gs_path}",
            size_before_kb=size_before,
        )
    except Exception as exc:
        return PrepressResult(
            success=False,
            output_path=output_path,
            steps_done=steps_done,
            error=f"Chyba pipeline: {exc}",
            size_before_kb=size_before,
        )


def run_prepress_in_place(
    pdf_path: str,
    options: PrepressOptions | None = None,
    gs_path: str = "/usr/bin/gs",
) -> PrepressResult:
    """
    Spustí pipeline a přepíše originál.
    Bezpečně — nejprve temp soubor, pak přepíše.
    """
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        result = run_prepress_pipeline(pdf_path, tmp_path, options, gs_path)
        if result.success:
            shutil.move(tmp_path, pdf_path)
            result.output_path = pdf_path
        else:
            Path(tmp_path).unlink(missing_ok=True)
        return result
    except Exception as exc:
        Path(tmp_path).unlink(missing_ok=True)
        return PrepressResult(success=False, output_path=pdf_path, error=str(exc))


# ---------------------------------------------------------------------------
# CMYK konverze args
# ---------------------------------------------------------------------------

_CMYK_PROFILES: dict[str, dict] = {
    "fogra39": {
        # ISO Coated v2 — standard pro ofsetový tisk
        # GS má profil coated_FOGRA39.icc (nebo je stáhneme)
        "icc_file": "coated_FOGRA39.icc",
        "label": "CMYK Fogra39 (ISO Coated v2)",
    },
    "fogra47": {
        "icc_file": "uncoated_FOGRA47.icc",
        "label": "CMYK Fogra47 (ISO Uncoated)",
    },
    "default": {
        "icc_file": None,
        "label": "CMYK (GS default)",
    },
}


def _build_cmyk_args(
    profile: str,
    gs_path: str,
) -> tuple[list[str], list[str], list[str]]:
    """
    Vrátí (gs_args, steps, warnings) pro CMYK konverzi.
    """
    steps = ["rgb_to_cmyk"]
    warnings: list[str] = []
    pinfo = _CMYK_PROFILES.get(profile, _CMYK_PROFILES["default"])

    # Základní CMYK převod — funguje vždy bez ICC
    base_args = [
        "-sColorConversionStrategy=CMYK",
        "-sColorConversionStrategyForImages=CMYK",
        "-dConvertCMYKImagesToRGB=false",
        "-dProcessColorModel=/DeviceCMYK",
    ]

    # Pokus o ICC profil
    icc_file = pinfo.get("icc_file")
    if icc_file:
        icc_path = _find_icc(icc_file)
        if icc_path:
            base_args += [
                f"--permit-file-read={icc_path}",  # bez toho -dSAFER profil nepustí
                f"-sOutputICCProfile={icc_path}",
                "-dRenderIntent=1",  # 1 = relativní kolorimetrický
            ]
            steps.append(f"icc_{profile}")
        else:
            # Zkusíme GS built-in
            # GS >= 9.x má default_cmyk_profile
            warnings.append(
                f"ICC profil {icc_file} nenalezen, používám GS default CMYK. "
                f"Pro přesné barvy nainstaluj color-icc-fogra39 nebo podobný balíček."
            )

    return base_args, steps, warnings


# ---------------------------------------------------------------------------
# Pomocné
# ---------------------------------------------------------------------------

def _gs_messages(output: str, limit: int = 3) -> tuple[list[str], list[str]]:
    """(chyby, varování) z výstupu GS. Chyba = řádek obsahující 'error'."""
    errors: list[str] = []
    warns: list[str] = []
    for ln in (line.strip() for line in output.splitlines()):
        if "error" in ln.lower():
            errors.append(ln[:300])
        elif ln.startswith("****"):
            warns.append(f"GS hlásí: {ln[:300]}")
    return errors[:limit], warns[:limit]


def _validate_output(input_p: Path, output_p: Path) -> tuple[str | None, list[str]]:
    """
    Vrátí (chyba, varování). Chyba = výstup nelze použít.
    Porovnává počet stran a rozměry stran (nezávisle na otočení).
    """
    import fitz  # PyMuPDF

    warns: list[str] = []
    try:
        out = fitz.open(str(output_p))
    except Exception as exc:
        return f"výstupní PDF nelze otevřít ({exc})", warns
    if out.page_count < 1:
        return "výstupní PDF nemá žádné stránky", warns

    try:
        src = fitz.open(str(input_p))
    except Exception:
        warns.append("Vstupní PDF nešlo přečíst pro kontrolu — počet stran a rozměry neověřeny.")
        return None, warns

    if src.is_repaired:
        warns.append(
            "Vstupní PDF je poškozené (při čtení muselo být opraveno) — "
            "zkontroluj, že výstup obsahuje všechny stránky a obsah."
        )

    if src.page_count != out.page_count:
        return f"počet stran nesedí (vstup {src.page_count}, výstup {out.page_count})", warns

    for i in range(src.page_count):
        a, b = src[i].mediabox, out[i].mediabox
        sa, sb = sorted((a.width, a.height)), sorted((b.width, b.height))
        if any(abs(x - y) > 2 for x, y in zip(sa, sb)):
            return (
                f"rozměr strany {i + 1} nesedí "
                f"(vstup {a.width:.0f}×{a.height:.0f} pt, výstup {b.width:.0f}×{b.height:.0f} pt)"
            ), warns
    return None, warns


def ghostscript_available(gs_path: str = "/usr/bin/gs") -> bool:
    try:
        r = subprocess.run([gs_path, "--version"], capture_output=True, timeout=5)
        return r.returncode == 0
    except Exception:
        return False


def ghostscript_version(gs_path: str = "/usr/bin/gs") -> str | None:
    try:
        r = subprocess.run([gs_path, "--version"], capture_output=True, text=True, timeout=5)
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:
        return None


# Zpětná kompatibilita — starý flattener nyní volá pipeline
def flatten_in_place(pdf_path: str, gs_path: str = "/usr/bin/gs") -> tuple[bool, str]:
    opts = PrepressOptions(
        flatten_text=True,
        flatten_transparency=False,
        convert_to_cmyk=False,
        compress=False,
        downsample_images=False,
    )
    r = run_prepress_in_place(pdf_path, opts, gs_path)
    return r.success, r.error or (", ".join(r.steps_done))
