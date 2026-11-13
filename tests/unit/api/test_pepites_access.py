"""
Les routes des pépites de Vany exigent un jeton, de compte ou d'invité (api/routers/pepites.py,
carte #103). Le routeur et les jetons sont les vrais ; les pépites en base sont remplacées.
Celles qui touchent un plan vérifient en plus son propriétaire : voir test_plan_access.py (carte #104).
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routers import pepites
from services.authentification import AUTH_COOKIE_NAME, create_access_token, create_guest_token

# Chaque route du routeur des pépites, avec sa méthode. La grille complète de toutes les routes viendra avec #106.
ROUTES = [
    ("GET", "/api/pepites/?plan_id=1&day_number=1"),
    ("GET", "/api/pepites/trail-tips?hike_ids=12"),
    ("GET", "/api/pepites/news?plan_id=1"),
    ("PUT", "/api/pepites/seen/1"),
    ("PUT", "/api/pepites/choose/1"),
]


@pytest.fixture
def client(monkeypatch):
    """Le routeur des pépites seul ; chaque lecture ou écriture en base répond vide."""
    for name in ("get_day_state", "trail_tips_for_hikes", "day_news", "mark_seen", "set_added"):
        monkeypatch.setattr(pepites.pepite_service, name, lambda *args, **kwargs: {})
    app = FastAPI()
    app.include_router(pepites.router, prefix="/api/pepites")
    return TestClient(app)


def call(client, method, path):
    body = {"json": {"day_number": 1, "pepite_id": 5}} if method == "PUT" else {}
    return client.request(method, path, **body)


@pytest.mark.parametrize("method,path", ROUTES)
def test_pepites_refused_without_token(client, method, path):
    """Sans cookie, les pépites de Vany répondent 401 : avant la carte #103, elles répondaient à n'importe qui."""
    assert call(client, method, path).status_code == 401


def test_trail_tips_open_to_a_guest(client):
    """Un voyageur sans compte, avec son jeton invité, reçoit les idées « en chemin » de ses randos."""
    client.cookies.set(AUTH_COOKIE_NAME, create_guest_token())
    assert call(client, "GET", "/api/pepites/trail-tips?hike_ids=12").status_code == 200


def test_trail_tips_open_to_an_account(client):
    """Un compte connecté reçoit aussi les idées « en chemin »."""
    client.cookies.set(AUTH_COOKIE_NAME, create_access_token({"user_id": 7, "username": "camille"}))
    assert call(client, "GET", "/api/pepites/trail-tips?hike_ids=12").status_code == 200
