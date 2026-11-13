"""
Connexion et déconnexion des comptes (contributeurs, admins).

Le jeton de connexion est posé dans un cookie httpOnly (services/authentification.py,
set_auth_cookie) : il n'apparaît jamais dans le JSON renvoyé, donc le JavaScript du front
ne le voit pas et ne peut pas le ranger dans le localStorage.
"""
from fastapi import APIRouter, Request, Body
from api.models.auth import UserLogin
from fastapi.responses import ORJSONResponse
from passlib.hash import bcrypt
from datetime import datetime, timedelta
from services.authentification import (
    ACCESS_TOKEN_EXPIRE_MINUTES, clear_auth_cookie, create_access_token, get_roles_for_user,
    get_user_by_username, insert_auth_log, set_auth_cookie,
)

router = APIRouter()

@router.post("/login", summary="Login user: the JWT is set in an httpOnly cookie")
async def login(request: Request, body: UserLogin = Body(...)) -> ORJSONResponse:
    """
    Vérifie le mot de passe, puis pose le jeton dans le cookie. La réponse donne seulement
    ce que le front affiche (nom, rôles) et l'heure d'expiration de la session.
    """
    username = body.username
    password = body.password
    user = get_user_by_username(username)
    if not user or not bcrypt.verify(password or "", user[2]):
        insert_auth_log(user[0] if user else None, username, "failed_login", "/auth/login", 401, token=None, filename=None)
        return ORJSONResponse(
            content={"success": False, "message": "Identifiants invalides"},
            status_code=401,
        )
    if not user[3]:
        insert_auth_log(user[0], user[1], "login_inactive", "/auth/login", 401, token=None, filename=None)
        return ORJSONResponse(
            content={"success": False, "message": "Utilisateur inactif"},
            status_code=401,
        )
    roles = list(get_roles_for_user(user[0]))
    token_data = {
        "user_id": user[0],
        "username": user[1],
        "roles": roles
    }
    expires_delta = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    token = create_access_token(token_data, expires_delta)
    expires_at = (datetime.utcnow() + expires_delta).isoformat() + "Z"
    insert_auth_log(user[0], user[1], "login", "/auth/login", 200, token=token, filename=None)
    response = ORJSONResponse(
        content={
            "success": True,
            "user": {"id": int(user[0]), "username": user[1], "roles": roles},
            "expires_at": expires_at
        }
    )
    set_auth_cookie(response, token)
    return response

@router.post("/logout", summary="Logout user: the cookie is cleared")
async def logout(request: Request) -> ORJSONResponse:
    """Efface le cookie de connexion : seul le serveur le peut, puisque le JavaScript ne le voit pas."""
    response = ORJSONResponse(content={"success": True, "message": "Logged out"})
    clear_auth_cookie(response)
    return response
