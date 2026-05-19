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
    "/usr/share/ghostscript/icc",
    "/usr/share/ghostscript",
    "/usr/share/color/icc",
    "/usr/lib/ghostscript",
]

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

        if result.returncode != 0:
            err = (result.stderr or result.stdout or "").strip()
            # Pokud je to jen warning, zkusíme pokračovat
            if output_p.exists() and output_p.stat().st_size > 1000:
                warnings.append(f"GS varování: {err[:300]}")
            else:
                return PrepressResult(
                    success=False,
                    output_path=output_path,
                    steps_done=steps_done,
                    warnings=warnings,
                    error=f"Ghostscript selhal (kód {result.returncode}): {err[:300]}",
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
    )
    r = run_prepress_in_place(pdf_path, opts, gs_path)
    return r.success, r.error or (", ".join(r.steps_done))
