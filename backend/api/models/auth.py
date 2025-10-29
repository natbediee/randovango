"""
Modèles Pydantic pour l'authentification et la gestion des utilisateurs
"""
from pydantic import BaseModel
from datetime import datetime


class UserLogin(BaseModel):
    """Modèle pour la connexion d'un utilisateur"""
    username : str
    password: str


class TokenResponse(BaseModel):
    """Modèle pour la réponse contenant un token JWT"""
    user_id: int
    username: str
    role: str
    token: str
    expires_at: datetime

class TokenRefresh(BaseModel):
    """Modèle pour le rafraîchissement d'un token"""
    token: str
    expires_at: datetime

