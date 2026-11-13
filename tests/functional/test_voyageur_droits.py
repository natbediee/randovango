"""
Droits du voyageur sur son voyage (features/voyageur_droits.feature, carte #87), à travers l'API.

Les routeurs, les jetons, le contrôle de propriété et les plafonds sont les vrais. Seules les bases
sont remplacées : les plans en mémoire (world.plans), les écritures et les recherches de Vany notées.
"""
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pytest_bdd import given, parsers, scenarios, then, when

from api import dependencies
from api.rate_limit import add_rate_limit
from api.routers import pepites, result, step1, step3
from services.authentification import AUTH_COOKIE_NAME, create_access_token

scenarios("features/voyageur_droits.feature")

# Les comptes des scénarios et leur user_id.
ACCOUNTS = {"Camille": 7, "Louis": 8}

# Ce que fait le voyageur sur un voyage : la route appelée, et le corps envoyé.
ACTIONS = {
    "ouvre le carnet de": ("GET", "/api/result/?plan_id={plan}", None),
    "choisit le spot de": ("PUT", "/api/step3/update_plan/{plan}", {"day_number": 1, "spot_id": 3}),
    "ajoute une pépite à": ("PUT", "/api/pepites/choose/{plan}", {"day_number": 1, "pepite_id": 5, "added": True}),
    "ouvre les pépites du jour de": ("GET", "/api/pepites/?plan_id={plan}&day_number=1", None),
}


class FakeCursor:
    """Curseur MySQL de test : la ville existe toujours, et chaque plan créé entre dans world.plans."""

    def __init__(self, plans: dict):
        self.plans = plans
        self.lastrowid = None

    def execute(self, sql, params=()):
        if sql.strip().startswith("INSERT INTO trip_plans"):
            # Colonnes : start_date, duration_days, city_id, user_token, user_id.
            self.lastrowid = len(self.plans) + 1
            self.plans[self.lastrowid] = {"user_id": params[4], "user_token": params[3]}

    def fetchone(self):
        return (1,)

    def close(self):
        pass


@pytest.fixture
def world(monkeypatch):
    """Ce que voit le scénario : les plans en base, les écritures, les recherches de Vany, la dernière réponse."""
    state = SimpleNamespace(plans={}, writes=[], searches=[], plan_id=None, response=None)

    def write(*args, **kwargs):
        state.writes.append(args)
        return {}

    def search(*args):
        state.searches.append(args)

    connection = SimpleNamespace(cursor=lambda **kwargs: FakeCursor(state.plans), commit=lambda: None,
                                 rollback=lambda: None)
    monkeypatch.setattr(step1.MySQLUtils, "connect", lambda: connection)
    monkeypatch.setattr(step1.MySQLUtils, "disconnect", lambda cnx: None)
    monkeypatch.setattr(step1, "start_zone_search", search)
    monkeypatch.setattr(step3, "insert_or_update_plan", write)
    monkeypatch.setattr(step3, "start_preparation", search)
    monkeypatch.setattr(result, "_fetch_plan_data", lambda plan_id: {"id": plan_id, "days": []})
    for name in ("get_day_state", "set_added"):
        monkeypatch.setattr(pepites.pepite_service, name, write)
    monkeypatch.setattr(dependencies, "get_plan_owner", state.plans.get)

    app = FastAPI()
    add_rate_limit(app)
    for router, prefix in ((step1, "step1"), (step3, "step3"), (result, "result"), (pepites, "pepites")):
        app.include_router(router.router, prefix=f"/api/{prefix}")
    state.client = TestClient(app)
    return state


def guest_token(name: str, expires_in: timedelta = timedelta(minutes=5)) -> str:
    """Le jeton invité d'un voyageur : son prénom tient lieu d'identifiant invité."""
    return create_access_token({"guest_id": name}, expires_in)


def account_token(name: str) -> str:
    return create_access_token({"user_id": ACCOUNTS[name], "username": name})


def create_trip(world, **extra):
    """Le voyageur du cookie crée un voyage de deux jours ; le plan créé devient « ce voyage »."""
    body = {"city_id": 5, "duration_days": 2, "start_date": "2027-06-01", **extra}
    world.response = world.client.post("/api/step1/create_plan", json=body)
    if world.response.status_code == 200:
        world.plan_id = world.response.json()["plan_id"]


# --- Étant donné ---

@given("un visiteur sans jeton")
def visitor_without_token(world):
    """Aucun cookie de connexion."""


@given(parsers.parse('l\'invité "{name}"'))
def guest(world, name):
    """Un voyageur sans compte, avec son jeton invité dans le cookie."""
    world.client.cookies.set(AUTH_COOKIE_NAME, guest_token(name))


@given(parsers.parse('l\'invité "{name}" dont le jeton a expiré'))
def guest_with_expired_token(world, name):
    """Un invité revenu après l'expiration de son jeton."""
    world.client.cookies.set(AUTH_COOKIE_NAME, guest_token(name, timedelta(minutes=-1)))


@given(parsers.parse('le compte "{name}"'))
def account(world, name):
    """Un compte connecté."""
    world.client.cookies.set(AUTH_COOKIE_NAME, account_token(name))


@given(parsers.parse('un voyage composé par l\'invité "{name}"'))
def trip_of_guest(world, name):
    """Un plan déjà en base, qui appartient à cet invité."""
    world.plan_id = 41
    world.plans[41] = {"user_id": 0, "user_token": name}


@given(parsers.parse('un voyage composé par le compte "{name}"'))
def trip_of_account(world, name):
    """Un plan déjà en base, qui appartient à ce compte."""
    world.plan_id = 41
    world.plans[41] = {"user_id": ACCOUNTS[name], "user_token": None}


@given("il a déjà créé un voyage aujourd'hui")
def already_created(world):
    """Le voyage gratuit du jour est déjà composé."""
    create_trip(world)


# --- Quand ---

@when("il crée un voyage")
def creates_trip(world):
    """Création d'un voyage, sans dire à qui il appartient : l'API le lit dans le jeton."""
    create_trip(world)


@when(parsers.parse('il crée un voyage en se déclarant le compte "{name}"'))
def creates_trip_as_someone_else(world, name):
    """Création d'un voyage avec un user_id glissé dans la demande."""
    create_trip(world, user_id=ACCOUNTS[name])


@when(parsers.parse("il {action} ce voyage"))
def acts_on_trip(world, action):
    """Une action du parcours sur « ce voyage » : carnet, spot, pépites."""
    method, path, body = ACTIONS[action]
    world.response = world.client.request(method, path.format(plan=world.plan_id), json=body)


@when(parsers.parse("il ouvre le carnet du voyage {plan_id:d}"))
def opens_trip_by_number(world, plan_id):
    """Le carnet d'un voyage désigné par son numéro."""
    world.response = world.client.get(f"/api/result/?plan_id={plan_id}")


# --- Alors ---

@then(parsers.parse("la réponse est {status:d}"))
def response_status(world, status):
    """Le code HTTP de la dernière réponse."""
    assert world.response.status_code == status


@then(parsers.parse('le plan appartient à l\'invité "{name}"'))
def belongs_to_guest(world, name):
    """Le plan porte l'identifiant invité de ce voyageur, et le user_id 0 des invités."""
    assert world.plans[world.plan_id] == {"user_id": 0, "user_token": name}


@then(parsers.parse('le plan appartient au compte "{name}"'))
def belongs_to_account(world, name):
    """Le plan porte le user_id de ce compte, sans identifiant invité."""
    assert world.plans[world.plan_id] == {"user_id": ACCOUNTS[name], "user_token": None}


@then("rien n'est écrit dans ce voyage")
def nothing_written(world):
    """Le refus a eu lieu avant la route : aucune écriture en base."""
    assert world.writes == []


@then("Vany lance une recherche")
def one_search(world):
    """La ville choisie met Vany au travail, une fois."""
    assert len(world.searches) == 1


@then("Vany ne lance aucune recherche")
def no_search(world):
    """Aucun appel d'agent n'est parti."""
    assert world.searches == []


@then("Vany ne lance qu'une seule recherche")
def only_one_search(world):
    """Le voyage refusé n'a pas relancé Vany : seule la recherche du premier voyage a eu lieu."""
    assert len(world.searches) == 1
