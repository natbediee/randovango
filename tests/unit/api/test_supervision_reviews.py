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
    monkeypatch.setattr(supervision_reviews.summary, "get_summary", lambda: {"spots": 3})
    app = FastAPI()
    app.include_router(supervision_reviews.router, prefix="/api/supervision")
    app.dependency_overrides[require_admin] = lambda: {"username": "camille"}
    return TestClient(app)


def test_the_summary_answers_an_admin(client):
    """Le bilan répond à un admin par les chiffres du service, sans rien changer en base."""
    response = client.get("/api/supervision/reviews/summary")
    assert response.status_code == 200
    assert response.json() == {"spots": 3}


@pytest.fixture
def reviews(monkeypatch):
    """Un client connecté en admin dont les relectures rendent ce qu'on leur a demandé, pour lire les filtres reçus."""
    monkeypatch.setattr(supervision_reviews.spots_review, "get_reviews", lambda: {"reviews": []})
    monkeypatch.setattr(supervision_reviews.services_review, "get_reviews",
                        lambda *args: {"demande": list(args)})
    monkeypatch.setattr(supervision_reviews.services_edit, "attach_sheets", lambda reviews: reviews)
    app = FastAPI()
    app.include_router(supervision_reviews.router, prefix="/api/supervision")
    app.dependency_overrides[require_admin] = lambda: {"username": "camille"}
    return TestClient(app)


def test_the_spot_reviews_answer_an_admin(reviews):
    """La page Spots reçoit les spots que l'agent propose de retirer."""
    response = reviews.get("/api/supervision/reviews/spots")
    assert response.status_code == 200
    assert response.json() == {"reviews": []}


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
