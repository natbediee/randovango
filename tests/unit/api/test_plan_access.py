"""
Contrôle de propriété des plans (api/dependencies.py require_plan_owner, carte #104 et #22) :
sans jeton 401, plan d'un autre 403, plan inexistant 404, son propre plan 200. Et create_plan
prend le propriétaire dans le jeton, jamais dans le corps de la requête.

Les routeurs et les jetons sont les vrais ; les plans en base et les recherches de Vany sont remplacés.
"""
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import dependencies
from api.routers import pepites, result, step1, step2, step3, step4
from services.authentification import AUTH_COOKIE_NAME, create_access_token

# Deux plans en base : le plan 1 est à un invité, le plan 2 à un compte (user_id 7).
GUEST_PLAN, ACCOUNT_PLAN, MISSING_PLAN = 1, 2, 99
OWNERS = {
    GUEST_PLAN: {"user_id": 0, "user_token": "invite-1"},
    ACCOUNT_PLAN: {"user_id": 7, "user_token": None},
}

# Chaque route qui lit ou modifie un plan, avec la place du numéro de plan dans l'adresse.
PLAN_ROUTES = [
    ("PUT", "/api/step1/update_day_city/{plan}"),
    ("PUT", "/api/step2/update_plan/{plan}"),
    ("PUT", "/api/step3/update_plan/{plan}"),
    ("PUT", "/api/step4/update_plan/{plan}"),
    ("GET", "/api/result/?plan_id={plan}"),
    ("GET", "/api/result/pdf?plan_id={plan}"),
    ("GET", "/api/pepites/?plan_id={plan}&day_number=1"),
    ("GET", "/api/pepites/news?plan_id={plan}"),
    ("PUT", "/api/pepites/seen/{plan}"),
    ("PUT", "/api/pepites/choose/{plan}"),
]
# Le carnet PDF n'est pas fabriqué dans les tests (WeasyPrint) : son accès refusé est testé, pas sa réussite.
READABLE_ROUTES = [route for route in PLAN_ROUTES if "/pdf" not in route[1]]


def guest_token(guest_id: str) -> str:
    return create_access_token({"guest_id": guest_id})


def account_token(user_id: int) -> str:
    return create_access_token({"user_id": user_id, "username": f"compte-{user_id}"})


@pytest.fixture
def world(monkeypatch):
    """Les routeurs du parcours ; chaque écriture en base est notée dans world.writes, sans base réelle."""
    state = SimpleNamespace(writes=[])

    def write(*args, **kwargs):
        state.writes.append(args)
        return {}

    monkeypatch.setattr(dependencies, "get_plan_owner", OWNERS.get)
    monkeypatch.setattr(step1, "set_day_city", write)
    monkeypatch.setattr(step1, "start_zone_search", write)
    monkeypatch.setattr(step2, "insert_or_update_plan", write)
    monkeypatch.setattr(step3, "insert_or_update_plan", write)
    monkeypatch.setattr(step3, "start_preparation", write)
    monkeypatch.setattr(step4, "insert_or_update_plan", write)
    monkeypatch.setattr(result, "_fetch_plan_data", lambda plan_id: {"days": []})
    for name in ("get_day_state", "day_news", "mark_seen", "set_added"):
        monkeypatch.setattr(pepites.pepite_service, name, write)

    app = FastAPI()
    for router, prefix in ((step1, "step1"), (step2, "step2"), (step3, "step3"), (step4, "step4"), (result, "result"), (pepites, "pepites")):
        app.include_router(router.router, prefix=f"/api/{prefix}")
    state.client = TestClient(app)
    return state


def call(world, method, path, plan, token=None):
    """Appelle une route de plan, avec le cookie de connexion si un jeton est donné."""
    if token:
        world.client.cookies.set(AUTH_COOKIE_NAME, token)
    body = {"json": {"day_number": 1, "city_id": 5, "pepite_id": 5}} if method == "PUT" else {}
    return world.client.request(method, path.format(plan=plan), **body)


@pytest.mark.parametrize("method,path", PLAN_ROUTES)
def test_plan_refused_without_token(world, method, path):
    """Sans cookie, aucune route de plan ne répond (401), et rien n'est écrit."""
    assert call(world, method, path, GUEST_PLAN).status_code == 401
    assert world.writes == []


@pytest.mark.parametrize("method,path", PLAN_ROUTES)
def test_guest_refused_on_another_guest_plan(world, method, path):
    """Un invité qui change le numéro de plan dans l'adresse tombe sur 403 : c'est la faille BOLA fermée."""
    assert call(world, method, path, GUEST_PLAN, guest_token("invite-2")).status_code == 403
    assert world.writes == []


@pytest.mark.parametrize("method,path", PLAN_ROUTES)
def test_account_refused_on_another_account_plan(world, method, path):
    """Un compte reçoit 403 sur le plan d'un autre compte."""
    assert call(world, method, path, ACCOUNT_PLAN, account_token(8)).status_code == 403
    assert world.writes == []


@pytest.mark.parametrize("method,path", PLAN_ROUTES)
def test_account_refused_on_a_guest_plan(world, method, path):
    """Un compte reçoit 403 sur le plan d'un invité : le user_id 0 des invités n'est celui d'aucun compte."""
    assert call(world, method, path, GUEST_PLAN, account_token(7)).status_code == 403


@pytest.mark.parametrize("method,path", PLAN_ROUTES)
def test_guest_refused_on_an_account_plan(world, method, path):
    """Un invité reçoit 403 sur le plan d'un compte, qui n'a pas d'identifiant invité."""
    assert call(world, method, path, ACCOUNT_PLAN, guest_token("invite-1")).status_code == 403


@pytest.mark.parametrize("method,path", PLAN_ROUTES)
def test_missing_plan_is_404(world, method, path):
    """Un numéro de plan qui n'existe pas répond 404, et rien n'est créé."""
    assert call(world, method, path, MISSING_PLAN, guest_token("invite-1")).status_code == 404
    assert world.writes == []


@pytest.mark.parametrize("method,path", READABLE_ROUTES)
def test_guest_reaches_own_plan(world, method, path):
    """Un invité lit et modifie son propre plan (200)."""
    assert call(world, method, path, GUEST_PLAN, guest_token("invite-1")).status_code == 200


@pytest.mark.parametrize("method,path", READABLE_ROUTES)
def test_account_reaches_own_plan(world, method, path):
    """Un compte lit et modifie son propre plan (200)."""
    assert call(world, method, path, ACCOUNT_PLAN, account_token(7)).status_code == 200


# --- Création du plan : le propriétaire vient du jeton ---

class FakeCursor:
    """Curseur MySQL de test : la ville existe toujours, et chaque plan créé est noté."""

    def __init__(self, created_plans: list):
        self.created_plans = created_plans
        self.lastrowid = 42

    def execute(self, sql, params=()):
        if sql.strip().startswith("INSERT INTO trip_plans"):
            self.created_plans.append(params)

    def fetchone(self):
        return (1,)

    def close(self):
        pass


@pytest.fixture
def created_plans(world, monkeypatch):
    """Les lignes trip_plans écrites par create_plan : (start_date, duration_days, city_id, user_token, user_id)."""
    plans = []
    connection = SimpleNamespace(cursor=lambda **kwargs: FakeCursor(plans), commit=lambda: None, rollback=lambda: None)
    monkeypatch.setattr(step1.MySQLUtils, "connect", lambda: connection)
    monkeypatch.setattr(step1.MySQLUtils, "disconnect", lambda cnx: None)
    return plans


def create_plan(world, token=None, **extra):
    if token:
        world.client.cookies.set(AUTH_COOKIE_NAME, token)
    body = {"city_id": 5, "duration_days": 2, "start_date": "2027-06-01", **extra}
    return world.client.post("/api/step1/create_plan", json=body)


def test_guest_plan_belongs_to_the_guest_token(world, created_plans):
    """Un plan créé par un invité porte son identifiant invité, et le user_id 0 des invités."""
    assert create_plan(world, guest_token("invite-1")).status_code == 200
    assert created_plans == [(date(2027, 6, 1), 2, 5, "invite-1", 0)]


def test_account_plan_belongs_to_the_account_token(world, created_plans):
    """Un plan créé par un compte porte son user_id, sans identifiant invité."""
    assert create_plan(world, account_token(7)).status_code == 200
    assert created_plans == [(date(2027, 6, 1), 2, 5, None, 7)]


def test_owner_sent_in_the_body_is_ignored(world, created_plans):
    """Un user_id ou un user_token glissé dans le corps est ignoré : avant, il créait un plan au nom d'un autre."""
    create_plan(world, guest_token("invite-1"), user_id=7, user_token="invite-2")
    assert created_plans == [(date(2027, 6, 1), 2, 5, "invite-1", 0)]


def test_plan_creation_refused_without_token(world, created_plans):
    """Sans cookie, aucun plan n'est créé (401), donc aucune recherche de Vany ne part."""
    assert create_plan(world).status_code == 401
    assert created_plans == []
    assert world.writes == []
