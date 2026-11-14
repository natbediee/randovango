"""
Les gestes sur une décision déjà prise : corriger son texte (PUT /decisions/{id}) et la dire juste
(POST /decisions/{id}/audit), carte #186.

Le routeur est le vrai ; l'admin connecté et les services sont remplacés : on regarde ce que la route transmet, ce
qu'elle répond, et ce qu'elle refuse. Les droits d'accès sont testés à part (tests/functional/test_supervision_droits.py).
"""
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.dependencies import require_admin
from api.routers import supervision_decisions


@pytest.fixture
def api(monkeypatch):
    """Un client de l'API des décisions, connecté en admin ; state.calls garde ce que reçoivent les services."""
    state = SimpleNamespace(calls=[], refuse=False)

    def record(*args):
        if state.refuse:
            raise ValueError("Décision de spot introuvable ou annulée")
        state.calls.append(args)

    monkeypatch.setattr(supervision_decisions.spots_review, "correct_a_savoir", record)
    monkeypatch.setattr(supervision_decisions.services_review, "confirm_audit", record)
    app = FastAPI()
    app.include_router(supervision_decisions.router, prefix="/api/supervision")
    app.dependency_overrides[require_admin] = lambda: {"username": "camille"}
    state.client = TestClient(app)
    return state


def test_a_corrected_text_reaches_the_spot_decision(api):
    """Le texte « À savoir » corrigé du parking du port arrive à sa décision, et la route répond par lui."""
    response = api.client.put("/api/supervision/decisions/55", json={"a_savoir": "Barrière la nuit"})
    assert response.status_code == 200
    assert response.json() == {"id": 55, "a_savoir": "Barrière la nuit"}
    assert api.calls == [(55, "Barrière la nuit")]


@pytest.mark.parametrize("body", [{}, {"a_savoir": None}, {"a_savoir": 3}])
def test_a_text_correction_without_text_is_refused(api, body):
    """Un corps sans texte, ou d'un autre type, est refusé (422) par le modèle, avant d'arriver au service."""
    assert api.client.put("/api/supervision/decisions/55", json=body).status_code == 422
    assert api.calls == []


def test_a_text_correction_on_another_decision_is_refused(api):
    """Le numéro d'une décision de service, ou d'une décision annulée, n'a pas de texte « À savoir » : 422."""
    api.refuse = True
    response = api.client.put("/api/supervision/decisions/2915", json={"a_savoir": ""})
    assert response.status_code == 422
    assert response.json()["detail"] == "Décision de spot introuvable ou annulée"


def test_a_rule_decision_can_be_marked_right(api):
    """« C'est juste » sur une décision de la règle tirée au sort : la route la transmet et répond par son numéro."""
    response = api.client.post("/api/supervision/decisions/71/audit")
    assert response.status_code == 200
    assert response.json() == {"id": 71}
    assert api.calls == [(71,)]


@pytest.mark.parametrize("method, path", [("PUT", "/edit/spots/decisions/55"), ("POST", "/services/audit/71")])
def test_the_old_routes_are_gone(api, method, path):
    """Les anciennes routes de correction et de contrôle n'existent plus : un seul chemin par geste."""
    assert api.client.request(method, f"/api/supervision{path}", json={}).status_code in (404, 405)
