"""
Connexion et déconnexion (api/routers/auth.py, carte #24) : le jeton part dans un cookie
httpOnly, jamais dans le JSON que lit le JavaScript du front.

Les comptes et le journal des connexions (SQLite) sont remplacés ; le mot de passe, le jeton
et le cookie sont les vrais.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from passlib.hash import bcrypt

from api.routers import auth

PASSWORD = "bon-mot-de-passe"
# Une ligne de la table users : id, username, password_hash, is_active.
ACCOUNT = (7, "camille", bcrypt.hash(PASSWORD), 1)


@pytest.fixture
def client(monkeypatch):
    """L'API de connexion seule, avec un compte « camille » admin."""
    monkeypatch.setattr(auth, "get_user_by_username", lambda username: ACCOUNT if username == "camille" else None)
    monkeypatch.setattr(auth, "get_roles_for_user", lambda user_id: {"admin"})
    monkeypatch.setattr(auth, "insert_auth_log", lambda *args, **kwargs: None)
    app = FastAPI()
    app.include_router(auth.router, prefix="/api/auth")
    return TestClient(app)


def login(client, password=PASSWORD):
    return client.post("/api/auth/login", json={"username": "camille", "password": password})


def test_login_puts_the_token_in_an_httponly_cookie(client):
    """La connexion pose le jeton dans un cookie que le JavaScript ne peut pas lire (httpOnly), réservé à l'API."""
    cookie = login(client).headers["set-cookie"].lower()
    assert cookie.startswith("access_token=")
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "path=/api" in cookie


def test_login_answer_has_no_token(client):
    """Le JSON de la connexion donne le nom, les rôles et l'heure de fin, mais plus le jeton, qui finissait dans le localStorage."""
    body = login(client).json()
    assert body["user"] == {"id": 7, "username": "camille", "roles": ["admin"]}
    assert "expires_at" in body
    assert "token" not in body


def test_wrong_password_sets_no_cookie(client):
    """Un mauvais mot de passe reçoit 401, sans cookie."""
    response = login(client, password="faux")
    assert response.status_code == 401
    assert "set-cookie" not in response.headers


def test_cookie_is_secure_by_default(client, monkeypatch):
    """Par défaut, le cookie ne part qu'en HTTPS (préprod, prod)."""
    monkeypatch.delenv("COOKIE_SECURE", raising=False)
    assert "secure" in login(client).headers["set-cookie"].lower()


def test_cookie_can_travel_over_http_in_development(client, monkeypatch):
    """COOKIE_SECURE=0 laisse passer le cookie en HTTP, pour le poste de développement (Safari sur http://localhost)."""
    monkeypatch.setenv("COOKIE_SECURE", "0")
    assert "secure" not in login(client).headers["set-cookie"].lower()


def test_logout_clears_the_cookie(client):
    """La déconnexion efface le cookie : seul le serveur le peut, le JavaScript ne le voit pas."""
    cookie = client.post("/api/auth/logout").headers["set-cookie"].lower()
    assert cookie.startswith('access_token=""') or cookie.startswith("access_token=;")
    assert "max-age=0" in cookie
    assert "path=/api" in cookie
