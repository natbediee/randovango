"""
Une seule route annule les décisions de la supervision : DELETE /decisions/{id} (carte #186).

Le routeur est le vrai ; l'admin connecté et l'annulation sont remplacés : on regarde que la route transmet le numéro
reçu, répond par la décision annulée, et rend 422 quand l'annulation est refusée. Les droits d'accès sont testés à
part (tests/functional/test_supervision_droits.py).
"""
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.dependencies import require_admin
from api.routers import supervision_decisions


@pytest.fixture
def api(monkeypatch):
    """Un client de l'API des décisions, connecté en admin ; state.cancelled garde les numéros reçus."""
    state = SimpleNamespace(cancelled=[], refuse=False)

    def cancel(decision_id):
        if state.refuse:
            raise ValueError("Décision introuvable ou déjà annulée")
        state.cancelled.append(decision_id)
        return {"id": decision_id, "objet_type": "poi", "objet_id": 48147}

    monkeypatch.setattr(supervision_decisions.decisions, "cancel_decision", cancel)
    app = FastAPI()
    app.include_router(supervision_decisions.router, prefix="/api/supervision")
    app.dependency_overrides[require_admin] = lambda: {"username": "camille"}
    state.client = TestClient(app)
    return state


def test_a_cancellation_answers_with_the_cancelled_decision(api):
    """Annuler la décision 55 sur un service : la route répond par cette décision, la page recharge ensuite sa liste."""
    response = api.client.delete("/api/supervision/decisions/55")
    assert response.status_code == 200
    assert response.json() == {"id": 55, "objet_type": "poi", "objet_id": 48147}
    assert api.cancelled == [55]


def test_a_refused_cancellation_answers_422(api):
    """Un double clic sur « annuler » : la décision déjà annulée est refusée (422), la page affiche le message."""
    api.refuse = True
    response = api.client.delete("/api/supervision/decisions/55")
    assert response.status_code == 422
    assert response.json()["detail"] == "Décision introuvable ou déjà annulée"


@pytest.mark.parametrize("path", ["/openings/55", "/services/decisions/55", "/edit/services/decisions/55",
                                  "/edit/spots/decisions/55", "/edit/spots/openings/55"])
def test_the_old_cancel_routes_are_gone(api, path):
    """Les cinq anciennes routes d'annulation, une par page, n'existent plus : un seul chemin pour annuler."""
    assert api.client.delete(f"/api/supervision{path}").status_code in (404, 405)
