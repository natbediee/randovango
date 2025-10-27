"""
Modèles Pydantic pour l'authentification et la gestion des utilisateurs
"""
from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from datetime import datetime


class UserRegister(BaseModel):
    """Modèle pour l'inscription d'un utilisateur"""
    email: EmailStr
    password: str = Field(..., min_length=8)
    nom: str = Field(..., min_length=2, max_length=100)
    prenom: str = Field(..., min_length=2, max_length=100)


class UserLogin(BaseModel):
    """Modèle pour la connexion d'un utilisateur"""
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    """Modèle pour la réponse contenant un token JWT"""
    user_id: int
    email: str
    role: str
    token: str
    expires_at: datetime


class TokenRefresh(BaseModel):
    """Modèle pour le rafraîchissement d'un token"""
    token: str
    expires_at: datetime


class UserInfo(BaseModel):
    """Modèle pour les informations d'un utilisateur"""
    user_id: int
    email: str
    nom: str
    prenom: str
    role: str
    plans_count: int
    traces_count: Optional[int] = 0
    created_at: datetime


class UserRole(BaseModel):
    """Modèle pour la modification du rôle d'un utilisateur"""
    role: str = Field(..., pattern="^(user|contributeur|admin)$")
