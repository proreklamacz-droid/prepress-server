"""
Zpráva pro zákazníka k výsledku preflightu.

Fakta (nálezy a rady) skládá vždy šablona z výsledků preflightu. LLM píše jen krátký
úvodní odstavec; když selže nebo jeho text neprojde kontrolou, použije se šablonový úvod.
Úvod: Strata (přes ollama-gate na ai-core) -> šablona. Zpráva vznikne vždy.
"""
import re

import httpx

from config import settings
from services.technologies import get_preset

SIGNATURE = "S pozdravem\nKrálovství tisku"

_VERDICT_TEXT = {
    "ok": "Váš soubor prošel automatickou kontrolou bez nalezených problémů.",
    "warning": (
        "Automatická kontrola našla v souboru drobné nedostatky. "
        "Doporučujeme je před tiskem opravit."
    ),
    "error": (
        "Automatická kontrola našla v souboru problémy, které je potřeba před tiskem opravit."
    ),
}

# Kontrola neověřuje všechno, takže nesmí slibovat „bez chyb / připraveno k tisku"
_NEVER_PROMISE = (
    "připraven k tisku", "připraveno k tisku", "připravená k tisku", "připravená data",
    "jakýchkoli problém", "jakýchkoliv problém", "bez chyb", "bezchyb", "dokonal",
)
_BAD_PHRASES_WHEN_PROBLEMS = ("v pořádku", "bez problém", "bez nedostatk")


# ---------------------------------------------------------------------------
# Nálezy (deterministicky z dat preflightu)
# ---------------------------------------------------------------------------

def _pages(items: list[dict]) -> str:
    pages = sorted({i.get("page") for i in items if i.get("page")})
    return ", ".join(str(p) for p in pages)


def build_findings(data: dict, preset: dict) -> list[dict]:
    """[{code, severity: error|warning, text}] — jen to, co preflight skutečně zjistil."""
    findings: list[dict] = []

    if not data.get("fonts_ok", True):
        n = len(data.get("fonts_issues") or [])
        findings.append({
            "code": "fonts",
            "severity": "error",
            "text": (
                f"V souboru nejsou vloženy některé fonty (nalezeno {n}). "
                "Prosím vložte fonty do PDF nebo převeďte text na křivky."
            ),
        })

    if not data.get("resolution_ok", True):
        min_dpi = data.get("resolution_min_dpi")
        pages = _pages(data.get("resolution_issues") or [])
        where = f" (strana {pages})" if pages else ""
        very_low = min_dpi is not None and min_dpi < 72
        findings.append({
            "code": "resolution",
            "severity": "error" if very_low else "warning",
            "text": (
                f"Některé obrázky mají nízké rozlišení{where}, nejnižší zjištěné je {min_dpi} dpi. "
                "Pro kvalitní tisk doporučujeme obrázky v rozlišení alespoň 300 dpi "
                "při výsledné tiskové velikosti."
                if min_dpi is not None else
                "Některé obrázky mají nízké rozlišení. Pro kvalitní tisk doporučujeme "
                "alespoň 300 dpi při výsledné tiskové velikosti."
            ),
        })

    if preset.get("colorspace") == "cmyk" and data.get("colorspace") in ("rgb", "mixed"):
        findings.append({
            "code": "colorspace",
            "severity": "warning",
            "text": (
                "Soubor obsahuje barvy v RGB. Pro tisk doporučujeme převod do CMYK; "
                "po převodu se mohou barvy mírně změnit, proto je dobré výsledek zkontrolovat."
            ),
        })

    tac_issues = data.get("ink_coverage_issues") or []
    if tac_issues:
        limit = tac_issues[0].get("limit")
        worst = max(i.get("tac", 0) for i in tac_issues)
        findings.append({
            "code": "tac",
            "severity": "warning",
            "text": (
                f"Na straně {_pages(tac_issues)} je celkové pokrytí barvou až {worst:g} % "
                f"(doporučený limit je {limit:g} %). Příliš sytých tmavých ploch se doporučuje "
                "zbavit, aby se barva při tisku nesmazávala."
            ),
        })

    return findings


# ---------------------------------------------------------------------------
# Úvodní odstavec: Strata -> šablona
# ---------------------------------------------------------------------------

def _intro_prompt(verdict: str, findings: list[dict]) -> str:
    lines = "\n".join(f"- {f['text']}" for f in findings) or "- (žádné)"
    return (
        "Jsi asistent tiskárny Království tisku. Napiš zákazníkovi úvod zprávy k výsledku "
        "automatické kontroly tiskových dat: 2 až 3 věty, česky, vykáním, přátelsky, "
        "bez markdownu a bez oslovení a podpisu. Nevymýšlej žádné další problémy, čísla "
        "ani sliby, použij jen fakta z nálezů. Nezmiňuj konkrétní tiskový stroj. "
        "Netvrď, že je soubor připraven k tisku ani že je zcela bez problémů, "
        "říkej jen, co kontrola našla nebo nenašla.\n\n"
        f"Verdikt kontroly: {verdict} (ok = bez problémů, warning = drobné nedostatky, "
        f"error = nutná oprava).\nNálezy:\n{lines}"
    )


def _call_strata(prompt: str) -> str | None:
    try:
        r = httpx.post(
            f"{settings.AI_CORE_OLLAMA_URL}/api/chat",
            json={
                "model": settings.CUSTOMER_MSG_MODEL,
                "stream": False,
                "think": False,
                "messages": [{"role": "user", "content": prompt}],
                "options": {"temperature": 0.3, "num_predict": 300},
            },
            timeout=settings.CUSTOMER_MSG_TIMEOUT_S,
        )
        r.raise_for_status()
        return r.json()["message"]["content"]
    except Exception:
        return None


def _valid_intro(text: str | None, verdict: str, findings: list[dict]) -> str | None:
    """Text z LLM projde jen když nic nepřidává a nepopírá nálezy."""
    if not text:
        return None
    text = text.strip()
    if not (20 <= len(text) <= 700):
        return None
    if re.search(r"[*#`_>|]", text):  # markdown
        return None
    # čísla v úvodu musí pocházet z nálezů
    allowed = set(re.findall(r"\d+", " ".join(f["text"] for f in findings)))
    if any(n not in allowed for n in re.findall(r"\d+", text)):
        return None
    low = text.lower()
    if any(p in low for p in _NEVER_PROMISE):
        return None
    if verdict != "ok" and any(p in low for p in _BAD_PHRASES_WHEN_PROBLEMS):
        return None
    return text


def generate_intro(verdict: str, findings: list[dict]) -> tuple[str, str]:
    """Vrací (text, zdroj) kde zdroj = strata | template."""
    text = _valid_intro(_call_strata(_intro_prompt(verdict, findings)), verdict, findings)
    if text:
        return text, "strata"
    return _VERDICT_TEXT.get(verdict, _VERDICT_TEXT["warning"]), "template"


# ---------------------------------------------------------------------------
# Složení zprávy
# ---------------------------------------------------------------------------

def render_body(intro: str, findings: list[dict]) -> str:
    parts = ["Dobrý den,", "", intro]
    if findings:
        parts += ["", "Co doporučujeme opravit:"]
        parts += [f"{i}. {f['text']}" for i, f in enumerate(findings, 1)]
        parts += ["", "Po úpravě nám prosím pošlete soubor znovu, rádi ho překontrolujeme."]
    parts += [
        "",
        "Jde o automatickou kontrolu, která neověřuje všechny možné problémy souboru.",
        "",
        SIGNATURE,
    ]
    return "\n".join(parts)


def data_from_result(pr) -> dict:
    """PreflightResult (DB řádek) -> dict ve tvaru, který vrací run_full_preflight."""
    keys = (
        "fonts_ok", "fonts_issues", "resolution_ok", "resolution_issues",
        "resolution_min_dpi", "colorspace", "ink_coverage_max", "ink_coverage_issues",
        "severity",
    )
    return {k: getattr(pr, k) for k in keys}


def build_customer_message(job, data: dict) -> dict:
    """Složí zprávu pro zákazníka. Nikdy nevyhazuje výjimku kvůli LLM."""
    preset = get_preset(job.technology)
    verdict = data.get("severity") or "warning"
    findings = build_findings(data, preset)
    intro, source = generate_intro(verdict, findings)
    return {
        "job_id": job.id,
        "status": "draft",
        "verdict": verdict,
        "subject": f"Kontrola tiskových dat: {job.source_filename}",
        "body": render_body(intro, findings),
        "findings": findings,
        "technology": job.technology,
        "source_filename": job.source_filename,
        "client_type": job.client_type,
        "client_id": job.client_id,
        "text_source": source,
    }
