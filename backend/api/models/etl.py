from typing import Optional
from pydantic import BaseModel

class GPXUploadResponse(BaseModel):
    success: bool
    message: str
    city: Optional[str] = None
    role: Optional[str] = None
    # Refus d'un tracé qui suit le chemin d'une rando déjà en base (issue #271) : le nom de cette rando, et si la
    # personne qui envoie (un admin) peut le charger quand même.
    same_path_hike: Optional[str] = None
    can_load_anyway: bool = False

class GPXDeleteResponse(BaseModel):
    success: bool
    message: str
    deleted_file: Optional[str] = None
