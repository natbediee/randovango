"""
Règles CORS de l'API (api/cors.py, carte #25) : seules les pages des origines prévues peuvent
appeler l'API avec le cookie de connexion, et seulement avec les méthodes et en-têtes utilisés.

Le middleware CORS est le vrai ; l'application ne contient qu'une route d'essai.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import cors

FRONT = "http://localhost:5003"


@pytest.fixture
def client(monkeypatch):
    """Une API avec les règles CORS, qui autorise seulement le front de branche."""
    monkeypatch.setenv("ALLOWED_ORIGINS", FRONT)
    app = FastAPI()
    cors.add_cors(app)

    @app.put("/api/essai")
    def essai():
        return {"ok": True}

    return TestClient(app)


def preflight(client, origin=FRONT, method="PUT", headers="content-type"):
    """La question préalable que pose le navigateur avant un PUT en JSON venu d'une autre origine."""
    return client.options("/api/essai", headers={
        "Origin": origin, "Access-Control-Request-Method": method, "Access-Control-Request-Headers": headers,
    })


def test_origins_are_read_without_spaces(monkeypatch):
    """Les origines de ALLOWED_ORIGINS sont lues sans les espaces ni les virgules en trop."""
    monkeypatch.setenv("ALLOWED_ORIGINS", " http://localhost , http://127.0.0.1,, ")
    assert cors.load_allowed_origins() == ["http://localhost", "http://127.0.0.1"]


def test_wildcard_origin_stops_the_api(monkeypatch):
    """« * » est refusé : avec le cookie de connexion, il ouvrirait l'API à tous les sites."""
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://localhost,*")
    with pytest.raises(RuntimeError, match="« \\* »"):
        cors.load_allowed_origins()


def test_front_may_call_the_api_with_its_cookie(client):
    """Le front prévu reçoit le feu vert, cookie compris (allow-credentials)."""
    response = preflight(client)
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == FRONT
    assert response.headers["access-control-allow-credentials"] == "true"


def test_other_site_is_refused(client):
    """La page d'un autre site n'a pas le feu vert : le navigateur bloque son appel avec le cookie du voyageur."""
    response = preflight(client, origin="https://site-piege.example")
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_other_site_cannot_read_an_answer(client):
    """Même sans question préalable, la réponse à un autre site ne porte pas l'autorisation : il ne peut pas la lire."""
    response = client.put("/api/essai", headers={"Origin": "https://site-piege.example"})
    assert "access-control-allow-origin" not in response.headers


def test_unused_method_is_refused(client):
    """Une méthode que l'API n'utilise pas (PATCH) est refusée, même depuis le front prévu."""
    assert preflight(client, method="PATCH").status_code == 400


def test_authorization_header_is_refused(client):
    """L'en-tête Authorization n'est plus accepté : le jeton passe par le cookie (carte #24)."""
    assert preflight(client, headers="authorization").status_code == 400
