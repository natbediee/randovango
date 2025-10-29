"""
Modèles Pydantic pour les randonnées
"""
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime


class HikeListItem(BaseModel):
    """Élément de liste de randonnée"""
    id: int
    name: str
    distance_km: float
    denivele_m: Optional[int] = 0
    difficulte: Optional[str] = None
    verifie: int  # 0=en_attente, 1=validee
    contributeur: Optional[str] = None
    date_ajout: datetime


class HikeDetail(BaseModel):
    """Détails complets d'une randonnée"""
    id: int
    name: str
    distance_km: float
    denivele_m: Optional[int] = 0
    difficulte: Optional[str] = None
    description: Optional[str] = None
    verifie: int
    contributeur_id: Optional[int] = None
    contributeur_nom: Optional[str] = None
    date_ajout: datetime
    gpx_preview: dict  # Coordonnées simplifiées pour affichage carte
    elevation_profile: Optional[List[dict]] = []
    pois_on_route: Optional[List[dict]] = []
    commentaire_admin: Optional[str] = None


class HikeUpload(BaseModel):
    """Réponse après upload d'une trace GPX"""
    status: str = "processing"
    job_id: str
    hike_id: int
    verifie: int = 0
    message: str


class Validation(BaseModel):
    """Validation ou rejet d'une trace par un admin"""
    commentaire: Optional[str] = None


class HikeValidated(BaseModel):
    """Réponse après validation d'une trace"""
    hike_id: int
    verifie: int
