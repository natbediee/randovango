
from fastapi import APIRouter, Request, Body
from api.models.auth import UserLogin
from fastapi.responses import ORJSONResponse
from passlib.hash import bcrypt
from datetime import datetime, timedelta
from services.authentification import (
    get_user_by_username, get_roles_for_user, insert_auth_log, create_access_token
)

router = APIRouter()

@router.post("/login", tags=["auth"], name="login")
async def login(request: Request, body: UserLogin = Body(...)) -> ORJSONResponse:
    username = body.login
    password = body.password
    user = get_user_by_username(username)
    if not user or not bcrypt.verify(password or "", user[2]):
        insert_auth_log(user[0] if user else None, username, "failed_login", "/auth/login", 401)
        return ORJSONResponse(
            content={"success": False, "message": "Identifiants invalides"},
            status_code=401,
        )
    if not user[3]:
        insert_auth_log(user[0], user[1], "login_inactive", "/auth/login", 401)
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
    expires_delta = timedelta(minutes=60)
    token = create_access_token(token_data, expires_delta)
    expires_at = (datetime.utcnow() + expires_delta).isoformat() + "Z"
    insert_auth_log(user[0], user[1], "login", "/auth/login", 200, token=token)
    return ORJSONResponse(
        content={
            "success": True,
            "user": {"id": int(user[0]), "username": user[1], "roles": roles},
            "token": token,
            "expires_at": expires_at
        }
    )

@router.post("/logout", tags=["auth"], name="logout")
async def logout(request: Request) -> ORJSONResponse:
    return ORJSONResponse(content={"success": True, "message": "Logged out"})
