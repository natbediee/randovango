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

from api import dependencies
from api.routers import supervision, supervision_bilan
from services.authentification import ALGORITHM, AUTH_COOKIE_NAME, SECRET_KEY, create_guest_token

scenarios("features/supervision_droits.feature")

USER = {"user_id": 7, "username": "camille"}


def token_for(user: dict, expires_in: timedelta = timedelta(minutes=5)) -> str:
    """Un jeton signé comme à la connexion, qui expire dans expires_in."""
    expires = datetime.now(timezone.utc) + expires_in
    return jwt.encode({**user, "exp": expires}, SECRET_KEY, algorithm=ALGORITHM)


@pytest.fixture
def world(monkeypatch):
    """Ce que voit le scénario : les rôles en base, les décisions reçues, la dernière réponse."""
    state = SimpleNamespace(roles=[], decisions=[], headers={}, response=None)

    def review_calls(*args, **kwargs):
        return {}

    def record(*args, **kwargs):
        state.decisions.append(args)

    monkeypatch.setattr(dependencies, "get_roles_for_user", lambda user_id: state.roles)
    monkeypatch.setattr(supervision.spots_review, "get_reviews", review_calls)
    monkeypatch.setattr(supervision.spots_review, "decide", record)
    monkeypatch.setattr(supervision.spots_review, "correct_a_savoir", record)
    monkeypatch.setattr(supervision.decisions, "cancel_decision", record)
    monkeypatch.setattr(supervision.services_review, "get_reviews", review_calls)
    monkeypatch.setattr(supervision.services_review, "decide", record)
    monkeypatch.setattr(supervision.services_review, "confirm_audit", record)
    monkeypatch.setattr(supervision_bilan.summary, "get_summary", review_calls)
    monkeypatch.setattr(supervision.services_edit, "search", review_calls)
    monkeypatch.setattr(supervision.services_edit, "decide", record)
    monkeypatch.setattr(supervision.services_edit, "decide_sheet", record)
    monkeypatch.setattr(supervision.services_edit, "get_sheet", review_calls)
    monkeypatch.setattr(supervision.services_edit, "attach_sheets", lambda reviews: reviews)
    monkeypatch.setattr(supervision.spots_edit, "search", review_calls)
    monkeypatch.setattr(supervision.spots_edit, "decide_opening", record)

    app = FastAPI()
    app.include_router(supervision.router, prefix="/api/supervision")
    app.include_router(supervision_bilan.router, prefix="/api/supervision")
    state.client = TestClient(app)
    return state


@given(parsers.parse("un visiteur avec un jeton {jeton}"))
def visitor(world, jeton):
    """Le cookie de connexion du visiteur : absent, faux ou expiré."""
    tokens = {
        "invalide": "pas-un-jeton",
        "expiré": token_for(USER, timedelta(minutes=-1)),
    }
    if jeton in tokens:
        world.client.cookies.set(AUTH_COOKIE_NAME, tokens[jeton])


@given(parsers.parse('un utilisateur connecté avec le rôle "{role}"'))
def connected(world, role):
    """Un compte connecté : le cookie porte un jeton valide, les rôles sont ceux de la base."""
    world.roles = [role]
    world.client.cookies.set(AUTH_COOKIE_NAME, token_for(USER))


@given("un admin qui envoie son jeton valide dans l'en-tête Authorization, sans cookie")
def bearer_header(world):
    """L'ancien envoi du jeton, par l'en-tête Authorization : il n'est plus lu (carte #24)."""
    world.roles = ["admin"]
    world.headers = {"Authorization": f"Bearer {token_for(USER)}"}


@given("un voyageur sans compte, avec son jeton invité")
def guest(world):
    """Un invité : son jeton est valide, mais il n'a pas de compte (carte #103)."""
    world.client.cookies.set(AUTH_COOKIE_NAME, create_guest_token())


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
    """La décision arrive au service au nom de l'admin connecté, sans note de pertinence (les deux None de la fin)."""
    assert world.decisions == [(spot, decision, "", USER["username"], None, None, None)]
