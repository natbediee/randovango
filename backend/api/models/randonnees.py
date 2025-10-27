"""
Modèles Pydantic pour les randonnées
"""
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime


class RandonneeListItem(BaseModel):
    """Élément de liste de randonnée"""
    id: int
    name: str
    distance_km: float
    denivele_m: Optional[int] = 0
    difficulte: Optional[str] = None
    verifie: int  # 0=en_attente, 1=validee, -1=rejetee
    contributeur: Optional[str] = None
    date_ajout: datetime


class RandonneeDetail(BaseModel):
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


class RandonneeUpload(BaseModel):
    """Réponse après upload d'une trace GPX"""
    status: str = "processing"
    job_id: str
    randonnee_id: int
    verifie: int = 0
    message: str


class RandonneeValidation(BaseModel):
    """Validation ou rejet d'une trace par un admin"""
    commentaire: Optional[str] = None


class RandonneeValidated(BaseModel):
    """Réponse après validation d'une trace"""
    randonnee_id: int
    verifie: int
    validated_at: datetime
    commentaire_admin: Optional[str] = None
