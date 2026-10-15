"""
Presety tiskových technologií pro preflight.
Zdroj dat: backend/presets/technologies.json (upravitelný bez změny kódu).

Pole presetu:
  label      — název pro UI
  warn_dpi   — fotky pod touto hodnotou = varování (pod 72 dpi je vždy chyba)
  max_tac    — limit celkového pokrytí barvou v % (null = neměřit proti limitu)
  colorspace — "cmyk" = RGB je varování, "any" = RGB je v pořádku
"""
import json
from pathlib import Path

DEFAULT_KEY = "default"
_PRESET_FILE = Path(__file__).resolve().parent.parent / "presets" / "technologies.json"


def load_presets() -> dict[str, dict]:
    with open(_PRESET_FILE, encoding="utf-8") as f:
        return json.load(f)


def get_preset(key: str | None) -> dict:
    """Vrátí preset; neznámý nebo prázdný klíč = výchozí."""
    presets = load_presets()
    return presets.get(key or DEFAULT_KEY) or presets[DEFAULT_KEY]


def is_valid_key(key: str) -> bool:
    return key in load_presets()
