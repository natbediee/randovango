"""
La fiche corrigée d'un service s'enregistre par PUT /services/{poi_id} (carte #186), depuis Modifier comme depuis une
carte de relecture.

Le routeur est le vrai ; l'admin connecté et le service sont remplacés : on regarde ce que la route transmet, ce
qu'elle répond, et ce qu'elle refuse. Les droits d'accès sont testés à part (tests/functional/test_supervision_droits.py).
"""
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.dependencies import require_admin
from api.routers import supervision_sheets


@pytest.fixture
def api(monkeypatch):
    """Un client de l'API des fiches, connecté en admin ; state.calls garde ce que reçoit decide_sheet."""
    state = SimpleNamespace(calls=[], refusal=None)

    def decide_sheet(poi_id, changes, note, decided_by, file):
        if state.refusal:
            raise ValueError(state.refusal)
        state.calls.append((poi_id, changes, note, decided_by, file))
        return sorted(changes)

    monkeypatch.setattr(supervision_sheets.services_edit, "decide_sheet", decide_sheet)
    app = FastAPI()
    app.include_router(supervision_sheets.router, prefix="/api/supervision")
    app.dependency_overrides[require_admin] = lambda: {"username": "camille"}
    state.client = TestClient(app)
    return state


def test_a_corrected_sheet_from_modifier_reaches_the_service(api):
    """Le lien Google Maps corrigé dans Modifier arrive au service, sans file ; la route répond par les champs changés."""
    body = {"changes": {"maps_url": "https://maps.app.goo.gl/abc"}, "note": "Vu sur place"}
    response = api.client.put("/api/supervision/services/48016", json=body)
    assert response.status_code == 200
    assert response.json() == {"poi_id": 48016, "champs": ["maps_url"]}
    assert api.calls == [(48016, {"maps_url": "https://maps.app.goo.gl/abc"}, "Vu sur place", "camille", None)]


def test_a_corrected_sheet_from_a_review_card_names_its_file(api):
    """Corriger le lien depuis la file « liens » transmet la file : corriger le champ mis en doute tranche le signal."""
    response = api.client.put("/api/supervision/services/2686", json={"changes": {"url": "https://a.fr"}, "file": "liens"})
    assert response.status_code == 200
    assert api.calls == [(2686, {"url": "https://a.fr"}, "", "camille", "liens")]


def test_a_too_long_link_is_refused_with_its_reason(api):
    """Un lien trop long est refusé (422) avec le motif du service, que la page affiche au lieu de couper le lien."""
    api.refusal = "Lien Google Maps : Lien trop long (612 caractères, 490 au plus)"
    response = api.client.put("/api/supervision/services/48016", json={"changes": {"maps_url": "https://x"}})
    assert response.status_code == 422
    assert response.json()["detail"].startswith("Lien Google Maps : Lien trop long")


@pytest.mark.parametrize("body", [{}, {"changes": None}, {"changes": "nom"}])
def test_a_sheet_without_changes_is_refused(api, body):
    """Un corps sans champs corrigés, ou d'un autre type, est refusé (422) par le modèle, avant d'arriver au service."""
    assert api.client.put("/api/supervision/services/48016", json=body).status_code == 422
    assert api.calls == []


@pytest.mark.parametrize("path", ["/services/fiche", "/edit/services/fiche"])
def test_the_old_sheet_routes_are_gone(api, path):
    """Les deux anciennes routes de la fiche, une par page, n'existent plus : une seule route pour la corriger."""
    assert api.client.post(f"/api/supervision{path}", json={}).status_code in (404, 405)
