"""
Les deux routes où la superviseuse tranche une proposition de l'agent reçoivent sa note de pertinence (carte #201).

Le routeur est le vrai ; l'admin connecté et les services sont remplacés : on regarde seulement ce que la route
transmet au service, et ce qu'elle refuse (400) sans rien enregistrer. Les droits d'accès sont testés à part
(tests/functional/test_supervision_droits.py).
"""
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.dependencies import require_admin
from api.routers import supervision


@pytest.fixture
def api(monkeypatch):
    """Un client de l'API de supervision, connecté en admin ; state.calls garde les décisions reçues par les services."""
    state = SimpleNamespace(calls=[])

    def record(*args):
        state.calls.append(args)

    monkeypatch.setattr(supervision.spots_review, "decide", record)
    monkeypatch.setattr(supervision.spots_review, "get_reviews", lambda: {})
    monkeypatch.setattr(supervision.services_review, "decide", record)
    monkeypatch.setattr(supervision, "service_reviews", lambda *args: {})
    app = FastAPI()
    app.include_router(supervision.router, prefix="/api/supervision")
    app.dependency_overrides[require_admin] = lambda: {"username": "camille"}
    state.client = TestClient(app)
    return state


def test_a_rated_spot_decision_passes_its_rating(api):
    """Une décision sur un spot notée « fausse, preuve faible » arrive au service avec sa note."""
    response = api.client.post("/api/supervision/decisions", json={
        "objet_id": 574, "decision": "garder", "pertinence": "fausse", "raison": "preuve_faible"})
    assert response.status_code == 200
    assert api.calls == [(574, "garder", "", "camille", None, "fausse", "preuve_faible")]


def test_an_empty_rating_is_no_rating(api):
    """Les listes laissées vides sur la page (chaînes vides) valent une décision non notée."""
    api.client.post("/api/supervision/decisions", json={"objet_id": 574, "decision": "retirer", "pertinence": "", "raison": ""})
    assert api.calls == [(574, "retirer", "", "camille", None, None, None)]


@pytest.mark.parametrize("rating", [{"pertinence": "parfaite"}, {"pertinence": "juste", "raison": "nom_adresse"},
                                    {"raison": "doublon_rate"}])
def test_a_wrong_spot_rating_is_refused_and_nothing_recorded(api, rating):
    """Une notation inconnue ou incohérente sur un spot est refusée (400), et la décision n'est pas enregistrée."""
    response = api.client.post("/api/supervision/decisions", json={"objet_id": 574, "decision": "garder", **rating})
    assert response.status_code == 400
    assert api.calls == []


def test_a_rated_service_decision_passes_its_rating(api):
    """Une décision sur un service notée « à corriger, nom ou adresse faux » arrive au service avec sa note."""
    response = api.client.post("/api/supervision/services/decisions", json={
        "tab": "fermetures", "poi_ids": [2686], "action": "retirer", "pertinence": "a_corriger", "raison": "nom_adresse"})
    assert response.status_code == 200
    assert api.calls == [("fermetures", [2686], "retirer", "", "camille", None, None, None, "a_corriger", "nom_adresse")]


def test_a_wrong_service_rating_is_refused_and_nothing_recorded(api):
    """Une raison inconnue sur un service est refusée (400), et la décision n'est pas enregistrée."""
    response = api.client.post("/api/supervision/services/decisions", json={
        "tab": "fermetures", "poi_ids": [2686], "action": "retirer", "pertinence": "fausse", "raison": "trop_loin"})
    assert response.status_code == 400
    assert api.calls == []


def test_a_batch_decision_cannot_be_rated(api):
    """Une décision par lot (liens cochés) n'est pas notée : une note juge une proposition, pas un lot (400)."""
    response = api.client.post("/api/supervision/services/decisions", json={
        "tab": "liens", "poi_ids": [12, 13], "action": "valider_lien", "pertinence": "juste"})
    assert response.status_code == 400
    assert api.calls == []
