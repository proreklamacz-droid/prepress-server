"""
Výstupní složka zpráv pro zákazníky: data/outbox/<job_id>/
  message.json, message.txt — obsah zprávy
  .ready                    — vzniká jako poslední; kdo čte, bere jen složky s .ready
Zápis je atomický (dočasný soubor + přejmenování).
"""
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from config import settings


def _dir(job_id: str) -> Path:
    return Path(settings.OUTBOX_DIR) / job_id


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def write_message(message: dict) -> None:
    d = _dir(message["job_id"])
    d.mkdir(parents=True, exist_ok=True)
    (d / ".ready").unlink(missing_ok=True)  # po dobu přepisu zpráva není k vyzvednutí

    message = {**message, "created_at": datetime.now(timezone.utc).isoformat()}
    _atomic_write(d / "message.json", json.dumps(message, ensure_ascii=False, indent=2))
    _atomic_write(d / "message.txt", f"Předmět: {message['subject']}\n\n{message['body']}\n")
    (d / ".ready").touch()


def read_message(job_id: str) -> dict | None:
    f = _dir(job_id) / "message.json"
    if not f.exists() or not (_dir(job_id) / ".ready").exists():
        return None
    return json.loads(f.read_text(encoding="utf-8"))


def delete_message(job_id: str) -> None:
    shutil.rmtree(_dir(job_id), ignore_errors=True)
