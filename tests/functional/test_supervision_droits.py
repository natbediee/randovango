"""
Droits d'accès de la supervision (features/supervision_droits.feature), à travers l'API.

Le routeur, l'authentification et les jetons sont les vrais. Seules les bases sont remplacées :
les rôles et les services de relecture, qui n'ont pas besoin des conteneurs.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jose import jwt
from pytest_bdd import given, parsers, scenarios, then, when

from api.routers import etl, supervision, supervision_bilan

scenarios("features/supervision_droits.feature")

USER = {"user_id": 7, "username": "camille"}


def token_for(user: dict, expires_in: timedelta = timedelta(minutes=5)) -> str:
    expires = datetime.now(timezone.utc) + expires_in
    return jwt.encode({**user, "exp": expires}, etl.SECRET_KEY, algorithm=etl.ALGORITHM)


@pytest.fixture
def world(monkeypatch):
    """Ce que voit le scénario : les rôles en base, les décisions reçues, la dernière réponse."""
    state = SimpleNamespace(roles=[], decisions=[], headers={}, response=None)

    def review_calls(*args, **kwargs):
        return {}

    def record(*args, **kwargs):
        state.decisions.append(args)

    monkeypatch.setattr(supervision, "get_roles_for_user", lambda user_id: state.roles)
    monkeypatch.setattr(supervision.supervision_service, "get_reviews", review_calls)
    monkeypatch.setattr(supervision.supervision_service, "decide", record)
    monkeypatch.setattr(supervision.supervision_service, "correct_a_savoir", record)
    monkeypatch.setattr(supervision.supervision_service, "cancel_decision", record)
    monkeypatch.setattr(supervision.poi_review_service, "get_reviews", review_calls)
    monkeypatch.setattr(supervision.poi_review_service, "decide", record)
    monkeypatch.setattr(supervision.poi_review_service, "confirm_audit", record)
    monkeypatch.setattr(supervision.poi_review_service, "cancel_decision", record)
    monkeypatch.setattr(supervision_bilan.supervision_summary_service, "get_summary", review_calls)
    monkeypatch.setattr(supervision.poi_edit_service, "search", review_calls)
    monkeypatch.setattr(supervision.poi_edit_service, "decide", record)
    monkeypatch.setattr(supervision.spot_edit_service, "search", review_calls)
    monkeypatch.setattr(supervision.spot_edit_service, "decide_opening", record)
    monkeypatch.setattr(supervision.supervision_service, "cancel_opening_decision", record)

    app = FastAPI()
    app.include_router(supervision.router, prefix="/api/supervision")
    app.include_router(supervision_bilan.router, prefix="/api/supervision")
    state.client = TestClient(app)
    return state


@given(parsers.parse("un visiteur avec un jeton {jeton}"))
def visitor(world, jeton):
    tokens = {
        "invalide": "pas-un-jeton",
        "expiré": token_for(USER, timedelta(minutes=-1)),
    }
    if jeton in tokens:
        world.headers = {"Authorization": f"Bearer {tokens[jeton]}"}


@given(parsers.parse('un utilisateur connecté avec le rôle "{role}"'))
def connected(world, role):
    world.roles = [role]
    world.headers = {"Authorization": f"Bearer {token_for(USER)}"}


@given("son rôle admin vient de lui être retiré")
def role_removed(world):
    world.roles = []


@when(parsers.parse("il appelle {methode} {route}"))
def call(world, methode, route):
    body = {"json": {}} if methode in ("POST", "PUT") else {}
    world.response = world.client.request(methode, route, headers=world.headers, **body)


@when(parsers.parse('il décide de "{decision}" le spot {spot:d}'))
def decide(world, decision, spot):
    world.response = world.client.post("/api/supervision/decisions", headers=world.headers,
                                       json={"objet_id": spot, "decision": decision})


@then(parsers.parse("la réponse est {status:d}"))
def response_status(world, status):
    assert world.response.status_code == status


@then("aucune décision n'est enregistrée")
def nothing_recorded(world):
    assert world.decisions == []


@then(parsers.parse('la décision "{decision}" sur le spot {spot:d} est enregistrée au nom de l\'utilisateur'))
def recorded(world, decision, spot):
    assert world.decisions == [(spot, decision, "", USER["username"], None)]
