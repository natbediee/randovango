"""
Les routes des passages des chaînes d'agents (api/routers/supervision_passages.py, issue #204) : lancer un passage,
suivre son état, le reprendre.

Le routeur est le vrai ; le service des passages est remplacé : on regarde ce que la route transmet, ce qu'elle répond
et ce qu'elle refuse. Aucun agent n'est appelé. Les refus 401 et 403 de chaque route sont dans la grille
(tests/functional/test_api_access.py) ; le dernier test refait le chemin entier avec un vrai jeton d'admin.
"""
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import dependencies
from api.dependencies import require_admin
from api.routers import supervision_passages
from services.authentification import AUTH_COOKIE_NAME, create_access_token
from services.passage_service import PassageConflict

PASSAGE_ID = "0123456789abcdef0123456789abcdef"


def state_of(passage_id: str, status: str = "en_file") -> dict:
    """Un état de passage, tel que le rend passage_service.read_passage (réduit à ce que les tests regardent)."""
    return {"passage_id": passage_id, "chaine": "services", "etat": status, "origine": "supervision",
            "ville": {"id": 12, "nom": "Guidel", "commune": "Guidel"}, "categories": []}


@pytest.fixture
def api(monkeypatch):
    """Un client des routes des passages, connecté en admin ; state note les passages créés, lancés et repris."""
    state = SimpleNamespace(created=[], ran=[], resumed=[], conflict=None, refusal=None, known={PASSAGE_ID})
    service = supervision_passages.passage_service

    def create_passage(chain, city_id, parts, origin):
        if state.refusal:
            raise ValueError(state.refusal)
        if state.conflict:
            raise PassageConflict(state.conflict)
        state.created.append((chain, city_id, parts, origin))
        state.known.add("nouveau")
        return "nouveau"

    def resume_passage(passage_id, origin):
        if state.conflict:
            raise PassageConflict(state.conflict)
        if passage_id not in state.known:
            return None
        state.resumed.append((passage_id, origin))
        return "reprise"

    monkeypatch.setattr(service, "create_passage", create_passage)
    monkeypatch.setattr(service, "resume_passage", resume_passage)
    monkeypatch.setattr(service, "run_passage", state.ran.append)
    monkeypatch.setattr(service, "read_passage", lambda passage_id: state_of(passage_id) if passage_id in state.known | {"reprise"} else None)
    monkeypatch.setattr(service, "list_passages", lambda limit: {"en_cours": [], "en_file": [state_of("nouveau")], "derniers": [], "limite": limit})
    app = FastAPI()
    app.include_router(supervision_passages.router, prefix="/api/supervision")
    app.dependency_overrides[require_admin] = lambda: {"username": "camille"}
    state.client = TestClient(app)
    return state


def test_a_launch_answers_at_once_and_runs_the_passage_in_the_background(api):
    """Le lancement répond tout de suite (202) par l'état « en file » du passage, puis le passage part en tâche de fond."""
    body = {"chaine": "services", "ville_id": 12, "categories": ["restaurants", "laveries"]}
    response = api.client.post("/api/supervision/passages", json=body)
    assert response.status_code == 202
    assert response.json()["passage_id"] == "nouveau" and response.json()["etat"] == "en_file"
    assert api.created == [("services", 12, ["restaurants", "laveries"], "supervision")]
    assert api.ran == ["nouveau"]


def test_a_launch_is_always_a_real_update(api):
    """Un champ d'essai envoyé par la page est ignoré : depuis la supervision, un passage enregistre toujours ce qu'il trouve."""
    api.client.post("/api/supervision/passages", json={"chaine": "services", "ville_id": 12, "essai": True})
    assert api.created == [("services", 12, None, "supervision")]


def test_a_launch_while_a_passage_runs_gets_a_clear_message(api):
    """Si un passage tourne déjà, le lancement est refusé (409) avec le message qui le nomme, et rien ne part."""
    api.conflict = "Un passage « Recherche des services » tourne déjà sur Guidel, depuis le 19/11/2026 à 10 h 05"
    response = api.client.post("/api/supervision/passages", json={"chaine": "services", "ville_id": 12})
    assert response.status_code == 409
    assert response.json()["detail"].startswith("Un passage « Recherche des services » tourne déjà sur Guidel")
    assert api.ran == []


@pytest.mark.parametrize("body", [{"chaine": "services"}, {"chaine": "services", "ville_id": "Guidel"}])
def test_a_launch_without_a_valid_city_is_refused(api, body):
    """Sans ville, ou avec un nom à la place de son numéro, le lancement est refusé (422) avant d'entrer dans la route."""
    assert api.client.post("/api/supervision/passages", json=body).status_code == 422
    assert api.created == []


def test_an_unknown_chain_is_refused_with_its_reason(api):
    """Une chaîne pas encore branchée est refusée (422) avec le motif du service."""
    api.refusal = "Chaîne inconnue : pepites (attendu : services)"
    response = api.client.post("/api/supervision/passages", json={"chaine": "pepites", "ville_id": 12})
    assert response.status_code == 422 and response.json()["detail"].startswith("Chaîne inconnue : pepites")


def test_the_state_of_a_passage_is_read(api):
    """L'état d'un passage connu est rendu (200) ; un passage inconnu répond 404."""
    response = api.client.get(f"/api/supervision/passages/{PASSAGE_ID}")
    assert response.status_code == 200 and response.json()["ville"]["nom"] == "Guidel"
    assert api.client.get("/api/supervision/passages/inconnu").status_code == 404


def test_the_list_gives_running_queued_and_recent_passages(api):
    """La liste des passages rend les trois groupes de l'espace Agents, avec la limite demandée."""
    response = api.client.get("/api/supervision/passages?limite=5")
    assert response.status_code == 200
    assert response.json()["limite"] == 5 and response.json()["en_file"][0]["passage_id"] == "nouveau"


def test_a_failed_passage_is_resumed_in_the_background(api):
    """La reprise d'un passage en échec répond (202) par le nouveau passage, lancé en tâche de fond."""
    response = api.client.post(f"/api/supervision/passages/{PASSAGE_ID}/reprise")
    assert response.status_code == 202 and response.json()["passage_id"] == "reprise"
    assert api.resumed == [(PASSAGE_ID, "supervision")] and api.ran == ["reprise"]


def test_a_resume_that_cannot_start_is_refused(api):
    """Reprendre un passage inconnu répond 404 ; un passage qui n'est pas en échec, 409 avec le motif."""
    assert api.client.post("/api/supervision/passages/inconnu/reprise").status_code == 404
    api.conflict = "Ce passage est « fini » : seul un passage en échec se reprend."
    response = api.client.post(f"/api/supervision/passages/{PASSAGE_ID}/reprise")
    assert response.status_code == 409 and "seul un passage en échec" in response.json()["detail"]
    assert api.ran == []


def test_an_admin_with_a_real_token_launches_a_passage(api, monkeypatch):
    """Avec un vrai jeton de compte et le rôle admin relu en base, le lancement passe (202) : le chemin 401 / 403 / 200 est complet."""
    api.client.app.dependency_overrides.clear()
    monkeypatch.setattr(dependencies, "get_roles_for_user", lambda user_id: {"admin"})
    api.client.cookies.set(AUTH_COOKIE_NAME, create_access_token({"user_id": 1, "username": "camille"}))
    response = api.client.post("/api/supervision/passages", json={"chaine": "services", "ville_id": 12})
    assert response.status_code == 202 and api.ran == ["nouveau"]


@pytest.fixture
def settings(api, monkeypatch):
    """Le service du budget remplacé : saved note chaque changement demandé, avec le nom de l'admin."""
    saved = []

    def save_settings(changes, changed_by, reason=None):
        if changes.get("daily_budget_eur", 0) > 100:
            raise ValueError("Le plafond du jour ne peut pas dépasser l'enveloppe du mois.")
        saved.append((changes, changed_by) if reason is None else (changes, changed_by, reason))
        return {"services_apres_etl": changes.get("services_after_etl", True), "modifie_par": changed_by}

    budget = supervision_passages.budget_service
    monkeypatch.setattr(budget, "budget_state", lambda: {"services_apres_etl": True, "budget_atteint": None})
    monkeypatch.setattr(budget, "save_settings", save_settings)
    return saved


def test_the_settings_are_read_by_an_admin(api, settings):
    """Le réglage des agents et l'état du budget se lisent (200), et « reglage » n'est pas pris pour un passage."""
    response = api.client.get("/api/supervision/passages/reglage")
    assert response.status_code == 200 and response.json() == {"services_apres_etl": True, "budget_atteint": None}


def test_a_change_sends_only_the_fields_given_with_the_admin_name(api, settings):
    """Couper la mise à jour automatique n'envoie que ce champ, sous son nom de colonne, avec le nom de l'admin."""
    response = api.client.put("/api/supervision/passages/reglage", json={"services_apres_etl": False})
    assert response.status_code == 200 and response.json()["services_apres_etl"] is False
    assert settings == [({"services_after_etl": False}, "camille")]


@pytest.mark.parametrize("body", [{"plafond_du_jour_eur": -1}, {"plafond_du_jour_eur": 150}])
def test_a_wrong_amount_is_refused(api, settings, body):
    """Un montant négatif, ou un plafond du jour plus grand que l'enveloppe, est refusé (422) et rien ne change."""
    assert api.client.put("/api/supervision/passages/reglage", json=body).status_code == 422
    assert settings == []


def test_the_reason_of_a_change_goes_with_it(api, settings):
    """La raison libre écrite dans la supervision part avec le changement ; elle n'est pas prise pour un réglage."""
    api.client.put("/api/supervision/passages/reglage", json={"plafond_du_jour_eur": 5, "raison": "test du budget atteint"})
    assert settings == [({"daily_budget_eur": 5}, "camille", "test du budget atteint")]


def test_a_change_without_any_known_rate_is_refused(api, monkeypatch):
    """Sans aucun taux de la BCE, un montant en euros ne peut pas être converti : la route répond 503 et le dit."""
    def save_settings(changes, changed_by, reason=None):
        raise supervision_passages.RateUnavailable("aucun taux de la BCE connu")

    monkeypatch.setattr(supervision_passages.budget_service, "save_settings", save_settings)
    response = api.client.put("/api/supervision/passages/reglage", json={"plafond_du_jour_eur": 6})
    assert response.status_code == 503 and "Taux du dollar inconnu" in response.json()["detail"]
