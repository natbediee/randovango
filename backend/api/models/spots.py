"""
Modèles Pydantic pour les spots et services
"""
from pydantic import BaseModel
from typing import List, Optional


class SpotDetail(BaseModel):
    """Détails complets d'un spot"""
    id: int
    name: str
    type: str
    note: Optional[float] = None
    description: Optional[str] = None
    latitude: float
    longitude: float
    services: List[str] = []
    url: Optional[str] = None