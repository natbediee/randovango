"""
Les routes d'annulation de la supervision passent toutes par decisions.cancel_decision (carte #186).

Le routeur est le vrai ; l'admin connecté et l'annulation sont remplacés : on regarde seulement que chaque route
transmet le numéro reçu, et rend 422 quand l'annulation est refusée. Les droits d'accès sont testés à part
(tests/functional/test_supervision_droits.py).
"""
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.dependencies import require_admin
from api.routers import supervision

# Les six routes d'annulation d'aujourd'hui ; l'étape F du plan les remplacera par DELETE /decisions/{id}.
CANCEL_PATHS = ["/decisions/55", "/openings/55", "/services/decisions/55", "/edit/services/decisions/55",
                "/edit/spots/decisions/55", "/edit/spots/openings/55"]


@pytest.fixture
def api(monkeypatch):
    """Un client de l'API de supervision, connecté en admin ; state.cancelled garde les numéros reçus."""
    state = SimpleNamespace(cancelled=[], refuse=False)

    def cancel(decision_id):
        if state.refuse:
            raise ValueError("Décision introuvable ou déjà annulée")
        state.cancelled.append(decision_id)

    monkeypatch.setattr(supervision.decisions, "cancel_decision", cancel)
    monkeypatch.setattr(supervision.spots_review, "get_reviews", lambda: {})
    monkeypatch.setattr(supervision, "service_reviews", lambda *args: {})
    monkeypatch.setattr(supervision, "_edit_services", lambda data: {})
    monkeypatch.setattr(supervision, "_edit_spots", lambda data: {})
    app = FastAPI()
    app.include_router(supervision.router, prefix="/api/supervision")
    app.dependency_overrides[require_admin] = lambda: {"username": "camille"}
    state.client = TestClient(app)
    return state


@pytest.mark.parametrize("path", CANCEL_PATHS)
def test_every_cancel_route_uses_the_common_cancellation(api, path):
    """Chaque bouton « annuler » (spots, ouvertures, services, Modifier) passe par la même annulation, qui lit le type."""
    response = api.client.delete(f"/api/supervision{path}")
    assert response.status_code == 200
    assert api.cancelled == [55]


@pytest.mark.parametrize("path", CANCEL_PATHS)
def test_a_refused_cancellation_answers_422(api, path):
    """Un double clic sur « annuler » : la décision déjà annulée est refusée (422), la page peut le dire."""
    api.refuse = True
    response = api.client.delete(f"/api/supervision{path}")
    assert response.status_code == 422
    assert response.json()["detail"] == "Décision introuvable ou déjà annulée"
