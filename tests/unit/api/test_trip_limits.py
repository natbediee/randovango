"""
Les bornes des routes du voyage (api/trip_limits.py, issue #263, OWASP API4) : un séjour de 7 jours au plus,
un numéro de jour pris dans le séjour, un rayon de 25 km au plus, 7 randos au plus pour les idées de Vany.
Chaque refus répond 422 avec un message en français, sans rien écrire en base ni lancer Vany.

Les routeurs et les jetons sont les vrais ; les plans en base et les recherches de Vany sont remplacés.
"""
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import dependencies, trip_limits
from api.routers import pepites, step1, step2, step3, step4
from services.authentification import AUTH_COOKIE_NAME, create_access_token

# Le plan 1, à l'invité « invite-1 », dure 7 jours.
PLAN_DAYS = 7

# Les routes qui écrivent un jour du séjour, avec ce que chacune envoie en plus du numéro du jour.
DAY_ROUTES = [
    ("/api/step1/update_day_city/1", {"city_id": 5}),
    ("/api/step2/update_plan/1", {"hike_id": 12}),
    ("/api/step3/update_plan/1", {"spot_id": 3}),
    ("/api/step4/update_plan/1", {"services": [8]}),
]
# Les routes publiques qui cherchent autour d'une ville, dans un rayon distance_km.
RADIUS_ROUTES = ["/api/step1/cities", "/api/step2/hikes?city_id=1", "/api/step3/spots?city_id=1",
                 "/api/step4/poi?city_id=1"]


@pytest.fixture
def world(monkeypatch):
    """Les routeurs du voyage ; chaque écriture en base, recherche de Vany ou connexion à la base est notée."""
    state = SimpleNamespace(writes=[], searches=[], plans=[], connections=[])

    def write(*args):
        state.writes.append(args)
        return 1

    def search(*args):
        state.searches.append(args)

    def connect():
        # La seule connexion attendue est celle de create_plan : elle vérifie la ville et écrit le plan.
        state.connections.append(True)
        cursor = SimpleNamespace(lastrowid=42, fetchone=lambda: (1,), close=lambda: None,
                                 execute=lambda sql, params=(): state.plans.append(params)
                                 if sql.strip().startswith("INSERT INTO trip_plans") else None)
        return SimpleNamespace(cursor=lambda **kwargs: cursor, commit=lambda: None, rollback=lambda: None)

    monkeypatch.setattr(step1.MySQLUtils, "connect", connect)
    monkeypatch.setattr(step1.MySQLUtils, "disconnect", lambda cnx: None)
    monkeypatch.setattr(dependencies, "get_plan_owner", lambda plan_id: {"user_id": 0, "user_token": "invite-1"})
    monkeypatch.setattr(trip_limits, "get_trip_duration", lambda plan_id: PLAN_DAYS)
    monkeypatch.setattr(step1, "set_day_city", write)
    monkeypatch.setattr(step1, "start_zone_search", search)
    for router in (step2, step3, step4):
        monkeypatch.setattr(router, "insert_or_update_plan", write)
    monkeypatch.setattr(step3, "start_preparation", search)
    monkeypatch.setattr(pepites.pepite_service, "trail_tips_for_hikes", lambda ids: {})

    app = FastAPI()
    for router, prefix in ((step1, "step1"), (step2, "step2"), (step3, "step3"), (step4, "step4"),
                           (pepites, "pepites")):
        app.include_router(router.router, prefix=f"/api/{prefix}")
    state.client = TestClient(app)
    state.client.cookies.set(AUTH_COOKIE_NAME, create_access_token({"guest_id": "invite-1"}))
    return state


def create_plan(world, days):
    return world.client.post("/api/step1/create_plan", json={"city_id": 5, "duration_days": days})


# --- La durée du séjour ---

def test_seven_day_trip_is_created(world):
    """Un séjour de 7 jours, le plus long de l'offre gratuite, est créé et Vany se met au travail."""
    assert create_plan(world, 7).status_code == 200
    assert [plan[1] for plan in world.plans] == [7]
    assert len(world.searches) == 1


def test_eight_day_trip_is_refused_with_a_clear_message(world):
    """Un séjour de 8 jours est refusé (422) : le message parle de l'offre gratuite et de l'offre payante à venir."""
    response = create_plan(world, 8)
    assert response.status_code == 422
    assert response.json() == {"detail": trip_limits.TRIP_TOO_LONG_MESSAGE}
    assert "7 jours" in trip_limits.TRIP_TOO_LONG_MESSAGE and "offre payante" in trip_limits.TRIP_TOO_LONG_MESSAGE


def test_huge_trip_writes_nothing(world):
    """Un séjour de 10 000 jours n'écrit ni plan ni jour, et ne lance pas Vany : avant, chaque jour devenait une ligne."""
    create_plan(world, 10_000)
    assert world.connections == []
    assert world.plans == []
    assert world.searches == []


# --- Le numéro du jour ---

@pytest.mark.parametrize("path,extra", DAY_ROUTES)
def test_day_of_the_trip_is_accepted(world, path, extra):
    """Le dernier jour du séjour (le 7e d'un séjour de 7 jours) s'enregistre normalement."""
    assert world.client.put(path, json={"day_number": PLAN_DAYS, **extra}).status_code == 200
    assert len(world.writes) == 1


@pytest.mark.parametrize("day_number", [0, PLAN_DAYS + 1, 999, -1, "abc", 2.5, True])
@pytest.mark.parametrize("path,extra", DAY_ROUTES)
def test_day_outside_the_trip_is_refused(world, path, extra, day_number):
    """Un jour hors du séjour (jour 999 d'un séjour de 7 jours, « abc ») est refusé : aucune ligne, aucune recherche de Vany."""
    response = world.client.put(path, json={"day_number": day_number, **extra})
    assert response.status_code == 422
    assert world.writes == []
    assert world.searches == []


def test_day_refusal_says_which_day(world):
    """Le refus d'un jour hors du séjour dit quel jour est refusé et combien de jours compte le séjour."""
    response = world.client.put("/api/step1/update_day_city/1", json={"day_number": 9, "city_id": 5})
    assert response.json() == {"detail": "Le jour 9 ne fait pas partie de ce séjour de 7 jours."}


# --- Le rayon de recherche ---

@pytest.mark.parametrize("radius", ["26", "5000", "0", "-3", "nan", "inf"])
@pytest.mark.parametrize("path", RADIUS_ROUTES)
def test_radius_outside_the_limit_is_refused(world, path, radius):
    """Un rayon de 5 000 km (toute la base d'un coup), nul ou négatif est refusé (422) avant d'ouvrir la base."""
    separator = "&" if "?" in path else "?"
    response = world.client.get(f"{path}{separator}distance_km={radius}")
    assert response.status_code == 422
    assert response.json() == {"detail": trip_limits.RADIUS_MESSAGE}
    assert world.connections == []


@pytest.mark.parametrize("radius", [0.5, 5, 25])
def test_radius_up_to_25_km_is_accepted(radius):
    """Un rayon jusqu'à 25 km est accepté, 5 km (celui de la page) compris."""
    trip_limits.check_radius(radius)


def test_radius_is_5_km_by_default():
    """Sans rayon dans l'adresse, la recherche se fait à 5 km de la ville, comme avant."""
    assert trip_limits.DEFAULT_RADIUS_KM == 5


# --- Les idées de Vany sur le chemin des randos ---

def test_trail_tips_for_seven_hikes(world):
    """Les idées de Vany se demandent pour 7 randos, une par jour d'un séjour gratuit."""
    assert world.client.get("/api/pepites/trail-tips?hike_ids=1,2,3,4,5,6,7").status_code == 200


def test_trail_tips_for_eight_hikes_are_refused(world):
    """Au-delà de 7 randos, la demande d'idées de Vany est refusée (422) avec un message en français."""
    response = world.client.get("/api/pepites/trail-tips?hike_ids=1,2,3,4,5,6,7,8")
    assert response.status_code == 422
    assert response.json() == {"detail": trip_limits.TOO_MANY_HIKES_MESSAGE}
