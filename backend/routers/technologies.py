"""Seznam tiskových technologií (presetů) pro preflight."""
from fastapi import APIRouter

from services.technologies import load_presets

router = APIRouter(prefix="/api/technologies", tags=["technologies"])


@router.get("")
def list_technologies():
    return [{"key": key, **preset} for key, preset in load_presets().items()]
