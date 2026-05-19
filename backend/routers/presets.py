"""
Imposition Presets — CRUD pro pojmenované předvolby nastavení imposice.

GET    /api/presets           — seznam všech presetů
POST   /api/presets           — vytvořit nový preset
GET    /api/presets/{id}      — detail presetu
PUT    /api/presets/{id}      — přejmenovat / aktualizovat
DELETE /api/presets/{id}      — smazat preset
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from models.job import ImpositionPreset

router = APIRouter(prefix="/api/presets", tags=["presets"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class PresetCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    description: str | None = None
    settings: dict  # celé ImpositionRequestBody jako dict


class PresetUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = None
    settings: dict | None = None


# ---------------------------------------------------------------------------
# GET /api/presets
# ---------------------------------------------------------------------------

@router.get("")
def list_presets(db: Session = Depends(get_db)):
    presets = db.query(ImpositionPreset).order_by(ImpositionPreset.name).all()
    return [_to_dict(p) for p in presets]


# ---------------------------------------------------------------------------
# POST /api/presets
# ---------------------------------------------------------------------------

@router.post("", status_code=201)
def create_preset(body: PresetCreate, db: Session = Depends(get_db)):
    # Unikátní název
    existing = db.query(ImpositionPreset).filter(ImpositionPreset.name == body.name).first()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Preset s názvem '{body.name}' již existuje.",
        )
    preset = ImpositionPreset(
        name=body.name,
        description=body.description,
        settings=body.settings,
    )
    db.add(preset)
    db.commit()
    db.refresh(preset)
    return _to_dict(preset)


# ---------------------------------------------------------------------------
# GET /api/presets/{preset_id}
# ---------------------------------------------------------------------------

@router.get("/{preset_id}")
def get_preset(preset_id: str, db: Session = Depends(get_db)):
    return _to_dict(_get_or_404(preset_id, db))


# ---------------------------------------------------------------------------
# PUT /api/presets/{preset_id}
# ---------------------------------------------------------------------------

@router.put("/{preset_id}")
def update_preset(preset_id: str, body: PresetUpdate, db: Session = Depends(get_db)):
    preset = _get_or_404(preset_id, db)

    if body.name is not None and body.name != preset.name:
        conflict = db.query(ImpositionPreset).filter(ImpositionPreset.name == body.name).first()
        if conflict:
            raise HTTPException(
                status_code=409,
                detail=f"Preset s názvem '{body.name}' již existuje.",
            )
        preset.name = body.name

    if body.description is not None:
        preset.description = body.description

    if body.settings is not None:
        preset.settings = body.settings

    db.commit()
    db.refresh(preset)
    return _to_dict(preset)


# ---------------------------------------------------------------------------
# DELETE /api/presets/{preset_id}
# ---------------------------------------------------------------------------

@router.delete("/{preset_id}")
def delete_preset(preset_id: str, db: Session = Depends(get_db)):
    preset = _get_or_404(preset_id, db)
    db.delete(preset)
    db.commit()
    return {"deleted": True, "id": preset_id}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_or_404(preset_id: str, db: Session) -> ImpositionPreset:
    p = db.query(ImpositionPreset).filter(ImpositionPreset.id == preset_id).first()
    if not p:
        raise HTTPException(status_code=404, detail=f"Preset {preset_id} nenalezen.")
    return p


def _to_dict(p: ImpositionPreset) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "description": p.description,
        "settings": p.settings,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }
