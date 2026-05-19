"""
LLM reporter — generates a human-readable Czech preflight report.
Primary: Groq API (llama-3.3-70b-versatile)
Fallback: rule-based text when Groq is unavailable or key is missing.
"""
import json
from config import settings


def build_prompt(data: dict) -> str:
    # Exclude the llm_report_cs field itself from the serialized payload
    clean = {k: v for k, v in data.items() if k != "llm_report_cs"}
    return (
        "Jsi expert na předtiskovou přípravu. Analyzuj výsledek preflight kontroly "
        "a napiš stručný, přátelský report v češtině. Popiš co je špatně a jak to opravit. "
        "Pokud je vše ok, napiš krátkou pochvalu.\n\n"
        f"Výsledky preflight:\n{json.dumps(clean, ensure_ascii=False, indent=2)}\n\n"
        "Piš přirozeně, bez markdown, max 3-4 věty."
    )


def build_fallback_report(data: dict) -> str:
    """Rule-based fallback when Groq is unavailable."""
    issues: list[str] = []

    if not data.get("fonts_ok", True):
        count = len(data.get("fonts_issues", []))
        issues.append(
            f"Nalezeny nevložené fonty ({count} {'problém' if count == 1 else 'problémy'})."
            " Před tiskem vložte nebo převeďte na křivky."
        )

    if not data.get("resolution_ok", True):
        min_dpi = data.get("resolution_min_dpi")
        if min_dpi:
            issues.append(
                f"Rozlišení obrázků je příliš nízké (minimum {min_dpi} DPI)."
                " Pro tisk je doporučeno alespoň 300 DPI."
            )
        else:
            issues.append(
                "Rozlišení obrázků nesplňuje požadavky pro tisk."
                " Nahraďte obrázky verzemi s vyšším rozlišením."
            )

    colorspace = data.get("colorspace")
    if colorspace == "rgb":
        issues.append(
            "Soubor obsahuje RGB barvy místo CMYK."
            " Před tiskem převeďte na CMYK v grafickém programu."
        )
    elif colorspace == "mixed":
        issues.append(
            "Soubor obsahuje kombinaci RGB a CMYK barev."
            " Doporučujeme sjednotit barevný model na CMYK."
        )

    if not issues:
        severity = data.get("severity", "ok")
        if severity == "ok":
            return "Soubor prošel základní kontrolou bez problémů. Vše je připraveno k tisku."
        return "Byly nalezeny drobné nesrovnalosti. Zkontrolujte podrobné výsledky."

    return "Nalezeny problémy: " + " ".join(issues)


async def generate_report(preflight_data: dict) -> str:
    """
    Generate Czech preflight report text.
    Tries Groq API first; falls back to rule-based text on any error.
    """
    if not settings.GROQ_API_KEY:
        return build_fallback_report(preflight_data)

    try:
        from groq import Groq

        client = Groq(api_key=settings.GROQ_API_KEY)
        prompt = build_prompt(preflight_data)

        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=600,
        )
        return response.choices[0].message.content

    except Exception:
        return build_fallback_report(preflight_data)
