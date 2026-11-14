"""
Les gestes de décision de la supervision (carte #186) : décider sur un spot ou ses dates d'ouverture
(POST /decisions), corriger le texte d'une décision (PUT /decisions/{id}) et la dire juste (POST /decisions/{id}/audit).

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
    monkeypatch.setattr(supervision_decisions.spots_review, "decide", record)
    monkeypatch.setattr(supervision_decisions.spots_edit, "decide_opening", record)
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


def test_a_spot_decision_reaches_the_spot_with_its_text(api):
    """Garder le parking du port avec un texte corrigé : la décision arrive au spot, et la route répond par elle."""
    body = {"objet": "spot", "objet_id": 1368, "decision": "garder", "note": "Vu sur Street View",
            "a_savoir": "Barrière la nuit"}
    response = api.client.post("/api/supervision/decisions", json=body)
    assert response.status_code == 200
    assert response.json()["objet_id"] == 1368
    assert api.calls == [(1368, "garder", "Vu sur Street View", "camille", "Barrière la nuit", None, None)]


def test_opening_dates_reach_the_spot(api):
    """Les dates d'ouverture tapées dans Modifier (1er avril au 31 octobre) arrivent au spot par la même route."""
    body = {"objet": "ouverture", "objet_id": 1368, "statut": "periode", "debut": "01/04", "fin": "31/10"}
    response = api.client.post("/api/supervision/decisions", json=body)
    assert response.status_code == 200
    assert api.calls == [(1368, "periode", "01/04", "31/10", "", "camille", False)]


@pytest.mark.parametrize("body", [
    {"objet_id": 1368, "decision": "garder"},                                     # sans objet
    {"objet": "pépite", "objet_id": 1368, "decision": "garder"},                  # objet inconnu
    {"objet": "spot", "objet_id": 1368, "decision": "supprimer"},                 # décision inconnue
    {"objet": "spot", "decision": "garder"},                                      # sans spot
    {"objet": "ouverture", "objet_id": 1368},                                     # ouverture sans statut
])
def test_a_malformed_decision_is_refused_before_the_service(api, body):
    """Un corps sans objet, d'un objet inconnu, ou à qui il manque un champ, est refusé (422) par le modèle."""
    assert api.client.post("/api/supervision/decisions", json=body).status_code == 422
    assert api.calls == []


def test_a_refused_spot_decision_answers_422(api):
    """Un spot inconnu est refusé par le service (422), avec son motif que la page affiche."""
    api.refuse = True
    response = api.client.post("/api/supervision/decisions", json={"objet": "spot", "objet_id": 1, "decision": "garder"})
    assert response.status_code == 422


@pytest.mark.parametrize("path", ["/edit/spots/decisions", "/edit/spots/openings"])
def test_the_old_spot_routes_are_gone(api, path):
    """Les deux anciennes routes de Modifier pour les spots n'existent plus : on décide par POST /decisions."""
    assert api.client.post(f"/api/supervision{path}", json={}).status_code in (404, 405)
