"""
Les routes des relectures de la supervision (/reviews/…) répondent à un admin (carte #186).

Le routeur est le vrai ; l'admin connecté et les services sont remplacés : on regarde seulement que la route répond
200 et rend ce que le service a calculé. Les refus 401 / 403 sont testés à part (tests/functional/test_api_access.py
et supervision_droits.feature).
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.dependencies import require_admin
from api.routers import supervision_reviews


@pytest.fixture
def client(monkeypatch):
    """Un client de l'API des relectures, connecté en admin ; le bilan rend un chiffre fixe."""
    monkeypatch.setattr(supervision_reviews.summary, "get_summary", lambda *args: {"spots": 3, "demande": list(args)})
    app = FastAPI()
    app.include_router(supervision_reviews.router, prefix="/api/supervision")
    app.dependency_overrides[require_admin] = lambda: {"username": "camille"}
    return TestClient(app)


def test_the_summary_answers_an_admin(client):
    """Le bilan répond à un admin par les chiffres du service, sans rien changer en base."""
    response = client.get("/api/supervision/reviews/summary")
    assert response.status_code == 200
    assert response.json() == {"spots": 3, "demande": [None, None]}


def test_the_summary_passes_the_city_or_the_town(client):
    """Le bilan de la ville n° 12, puis de la commune de Guilvinec : le filtre arrive tel quel au service."""
    assert client.get("/api/supervision/reviews/summary?ville=12").json()["demande"] == [12, None]
    assert client.get("/api/supervision/reviews/summary?commune=Guilvinec").json()["demande"] == [None, "Guilvinec"]


def test_an_unknown_city_in_the_summary_is_refused(monkeypatch, client):
    """Une ville qui n'existe pas est refusée (422), avec le motif du service."""
    def refuse(*args):
        raise ValueError("Ville inconnue : 999")
    monkeypatch.setattr(supervision_reviews.summary, "get_summary", refuse)
    response = client.get("/api/supervision/reviews/summary?ville=999")
    assert response.status_code == 422


@pytest.fixture
def reviews(monkeypatch):
    """Un client connecté en admin dont les relectures rendent ce qu'on leur a demandé, pour lire les filtres reçus."""
    monkeypatch.setattr(supervision_reviews.spots_review, "get_reviews", lambda *args: {"demande": list(args)})
    monkeypatch.setattr(supervision_reviews.services_review, "get_reviews",
                        lambda *args: {"demande": list(args)})
    monkeypatch.setattr(supervision_reviews.services_edit, "attach_sheets", lambda reviews: reviews)
    app = FastAPI()
    app.include_router(supervision_reviews.router, prefix="/api/supervision")
    app.dependency_overrides[require_admin] = lambda: {"username": "camille"}
    return TestClient(app)


def test_the_spot_reviews_answer_an_admin(reviews):
    """La page Spots sans filtre reçoit tous les spots que l'agent propose de retirer."""
    response = reviews.get("/api/supervision/reviews/spots")
    assert response.status_code == 200
    assert response.json() == {"demande": [None, None, None, None]}


def test_the_spot_reviews_pass_the_city_and_the_category(reviews):
    """Les spots gratuits de la ville n° 12 : la ville et la catégorie arrivent telles quelles au service."""
    response = reviews.get("/api/supervision/reviews/spots?ville=12&categorie=gratuit")
    assert response.json() == {"demande": [12, None, "gratuit", None]}


def test_the_spot_reviews_pass_a_town(reviews):
    """Une commune qui n'est pas une ville de l'appli (Guilvinec) arrive au service par « commune »."""
    response = reviews.get("/api/supervision/reviews/spots?commune=Guilvinec")
    assert response.json() == {"demande": [None, "Guilvinec", None, None]}


def test_the_spot_reviews_pass_the_problem(reviews):
    """Les spots non vérifiés seulement : le problème arrive tel quel au service."""
    response = reviews.get("/api/supervision/reviews/spots?probleme=non_verifie")
    assert response.json() == {"demande": [None, None, None, "non_verifie"]}


def test_an_unknown_spot_category_is_refused(monkeypatch, reviews):
    """Une catégorie que l'étape 3 ne connaît pas est refusée (422), avec le motif du service."""
    def refuse(*args):
        raise ValueError("Catégorie inconnue : luxe")
    monkeypatch.setattr(supervision_reviews.spots_review, "get_reviews", refuse)
    response = reviews.get("/api/supervision/reviews/spots?categorie=luxe")
    assert response.status_code == 422
    assert response.json()["detail"] == "Catégorie inconnue : luxe"


def test_the_service_reviews_pass_the_queue_and_the_filters(reviews):
    """La file « doublons » des restaurants du Conquet : la file et les filtres arrivent tels quels au service."""
    response = reviews.get("/api/supervision/reviews/services?file=doublons&service=restauration&ville=12&type=Crêperie")
    assert response.status_code == 200
    assert response.json() == {"demande": ["doublons", "restauration", "12", "Crêperie", None]}


def test_an_unknown_queue_is_refused(monkeypatch, reviews):
    """Une file qui n'existe pas est refusée (422), avec le message du service."""
    def unknown(*args):
        raise ValueError("File inconnue : poubelle")
    monkeypatch.setattr(supervision_reviews.services_review, "get_reviews", unknown)
    response = reviews.get("/api/supervision/reviews/services?file=poubelle")
    assert response.status_code == 422
    assert response.json()["detail"] == "File inconnue : poubelle"
