"""
Modèles Pydantic pour les randonnées
"""
from pydantic import BaseModel
from typing import Optional



class HikeListItem(BaseModel):
    """Élément de liste de randonnée"""
    id: int
    name: str
    distance_km: float
    estimated_duration_h: Optional[float] = None
    elevation_gain_m: Optional[int] = 0
    difficulte: Optional[str] = None
    start_latitude: Optional[float] = None
    start_longitude: Optional[float] = None
    mongo_id: Optional[str] = None
    trace: Optional[list] = None  # Liste de points (lat, lon, ele)
    verifie: int  # 0=en_attente, 1=validee