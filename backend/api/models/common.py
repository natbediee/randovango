"""
Modèles Pydantic utilitaires et réponses génériques
"""
from pydantic import BaseModel
from typing import Optional


class StatusResponse(BaseModel):
    """Réponse générique de statut"""
    status: str
    message: Optional[str] = None


class DeleteResponse(BaseModel):
    """Réponse après suppression"""
    status: str = "deleted"
    id: Optional[int] = None


class ETLJobResponse(BaseModel):
    """Réponse pour un job ETL"""
    status: str  # processing, completed, failed
    job_id: str
    progress: Optional[int] = None
    logs: Optional[list] = []
