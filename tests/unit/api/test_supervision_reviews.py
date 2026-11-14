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
