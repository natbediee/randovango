"""
Modèles Pydantic pour les spots et services
"""
from pydantic import BaseModel
from typing import List, Optional


class SpotListItem(BaseModel):
    """Élément de liste de spot"""
    id: int
    name: str
    type: str  # camping-car, bivouac, aire, etc.
    note: Optional[float] = None
    services: List[str] = []
    latitude: float
    longitude: float


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


class ServiceListItem(BaseModel):
    """Élément de liste de service/POI"""
    id: int
    name: str
    category: str  # restaurant, supermarche, pharmacie, etc.
    latitude: float
    longitude: float
    distance_km: Optional[float] = None


class ServiceDetail(BaseModel):
    """Détails complets d'un service"""
    id: int
    name: str
    category: str
    description: Optional[str] = None
    latitude: float
    longitude: float
    adresse: Optional[str] = None
    telephone: Optional[str] = None
    horaires: Optional[str] = None
