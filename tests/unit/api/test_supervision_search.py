"""
Les routes de recherche (/search/…) et la fiche d'un service (/services/{poi_id}) répondent à un admin (carte #186).

Les routeurs sont les vrais ; l'admin connecté et les services sont remplacés : on regarde ce que la route transmet au
service et ce qu'elle refuse. Les refus 401 / 403 sont testés à part (tests/functional/test_api_access.py et
supervision_droits.feature).
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.dependencies import require_admin
from api.routers import supervision_search, supervision_sheets


@pytest.fixture
def client(monkeypatch):
    """Un client connecté en admin dont les recherches rendent ce qu'on leur a demandé, pour lire les filtres reçus."""
    monkeypatch.setattr(supervision_search.services_edit, "search", lambda *args: {"services": list(args)})
    monkeypatch.setattr(supervision_search.spots_edit, "search", lambda *args: {"spots": list(args)})
    app = FastAPI()
    app.include_router(supervision_search.router, prefix="/api/supervision")
    app.include_router(supervision_sheets.router, prefix="/api/supervision")
    app.dependency_overrides[require_admin] = lambda: {"username": "camille"}
    return TestClient(app)


def test_the_service_search_passes_its_filters(client):
    """Les crêperies de Guilvinec, commune d'adresse sans ville de l'appli : filtres transmis, les vides comptent absents."""
    response = client.get("/api/supervision/search/services?service=restauration&type=Crêperie&nom=&commune=Guilvinec")
    assert response.status_code == 200
    assert response.json() == {"services": [None, "restauration", "Crêperie", None, "Guilvinec"]}


def test_the_spot_search_passes_the_city_and_the_name(client):
    """Les spots du Conquet dont le nom contient « port » : la ville et le nom arrivent au service."""
    response = client.get("/api/supervision/search/spots?ville=12&nom=port")
    assert response.status_code == 200
    assert response.json() == {"spots": [12, "port"]}


def test_a_refused_search_answers_422(monkeypatch, client):
    """Une recherche que le service refuse (ni ville ni nom) répond 422 avec son message."""
    def refuse(*args):
        raise ValueError("Choisis une ville ou tape un nom")
    monkeypatch.setattr(supervision_search.services_edit, "search", refuse)
    response = client.get("/api/supervision/search/services")
    assert response.status_code == 422
    assert response.json()["detail"] == "Choisis une ville ou tape un nom"


def test_the_sheet_of_a_service_answers_an_admin(monkeypatch, client):
    """La fiche de la Cave de Keruzas (n° 32498) : ce que voit le voyageur, pour la corriger."""
    monkeypatch.setattr(supervision_sheets.services_edit, "get_sheet", lambda poi_id: {"poi_id": poi_id})
    response = client.get("/api/supervision/services/32498")
    assert response.status_code == 200
    assert response.json() == {"poi_id": 32498}


def test_the_sheet_of_an_unknown_service_answers_404(monkeypatch, client):
    """Un service qui n'existe plus : 404, avec le message du service."""
    def unknown(poi_id):
        raise ValueError("Lieu inconnu")
    monkeypatch.setattr(supervision_sheets.services_edit, "get_sheet", unknown)
    response = client.get("/api/supervision/services/1")
    assert response.status_code == 404
