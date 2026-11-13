"""
Plafonds de débit des routes qui lancent les recherches de Vany (api/rate_limit.py, carte #21) :
au-delà du plafond, la réponse est 429 avec un message clair, et la route ne s'exécute pas.

Les routeurs, les jetons et slowapi sont les vrais ; les plans en base et les recherches de Vany
sont remplacés.
"""
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from api import dependencies, rate_limit
from api.routers import auth, step1, step3
from services.authentification import AUTH_COOKIE_NAME, create_access_token


def guest_token(guest_id: str) -> str:
    return create_access_token({"guest_id": guest_id})


@pytest.fixture
def world(monkeypatch):
    """Les routes plafonnées, compteurs remis à zéro ; chaque recherche de Vany lancée est notée."""
    state = SimpleNamespace(searches=[])
    rate_limit.limiter.reset()

    def search(*args):
        state.searches.append(args)

    connection = SimpleNamespace(cursor=lambda **kwargs: SimpleNamespace(
        execute=lambda *args: None, fetchone=lambda: (1,), close=lambda: None, lastrowid=42),
        commit=lambda: None, rollback=lambda: None)
    monkeypatch.setattr(step1.MySQLUtils, "connect", lambda: connection)
    monkeypatch.setattr(step1.MySQLUtils, "disconnect", lambda cnx: None)
    monkeypatch.setattr(step1, "start_zone_search", search)
    monkeypatch.setattr(step1, "set_day_city", lambda *args: None)
    monkeypatch.setattr(step3, "insert_or_update_plan", lambda plan_id, data: plan_id)
    monkeypatch.setattr(step3, "start_preparation", search)
    monkeypatch.setattr(dependencies, "get_plan_owner", lambda plan_id: {"user_id": 0, "user_token": "invite-1"})

    app = FastAPI()
    rate_limit.add_rate_limit(app)
    for router, prefix in ((auth, "auth"), (step1, "step1"), (step3, "step3")):
        app.include_router(router.router, prefix=f"/api/{prefix}")
    state.client = TestClient(app)
    yield state
    rate_limit.limiter.reset()


def create_plan(world, guest_id="invite-1"):
    world.client.cookies.set(AUTH_COOKIE_NAME, guest_token(guest_id))
    return world.client.post("/api/step1/create_plan", json={"city_id": 5, "duration_days": 2})


def test_fourth_plan_in_an_hour_is_refused(world):
    """Trois plans par heure passent ; le quatrième reçoit 429, et Vany ne lance pas de recherche de plus."""
    statuses = [create_plan(world).status_code for _ in range(4)]
    assert statuses == [200] * 3 + [429]
    assert len(world.searches) == 3


def test_plans_are_also_capped_per_day():
    """La création de plans a aussi un plafond par jour : 5, en plus des 3 par heure."""
    assert rate_limit.CREATE_PLAN_LIMIT == "3/hour;5/day"


def test_429_answer_is_clear(world):
    """La réponse 429 porte un message en français que le front affiche tel quel au voyageur."""
    for _ in range(3):
        create_plan(world)
    response = create_plan(world)
    assert response.json() == {"detail": "Tu vas un peu vite : trop de demandes en peu de temps. Réessaie dans un moment."}


def test_each_traveller_has_its_own_count(world):
    """Un voyageur au plafond ne bloque pas un autre voyageur, même sur le même wifi."""
    for _ in range(3):
        create_plan(world, "invite-1")
    assert create_plan(world, "invite-1").status_code == 429
    assert create_plan(world, "invite-2").status_code == 200


def test_day_city_is_capped(world):
    """Changer la ville du jour, qui relance les recherches de Vany, est plafonné à 15 fois par heure."""
    world.client.cookies.set(AUTH_COOKIE_NAME, guest_token("invite-1"))
    statuses = [world.client.put("/api/step1/update_day_city/1", json={"day_number": 1, "city_id": 5}).status_code
                for _ in range(16)]
    assert statuses == [200] * 15 + [429]


def test_day_spot_is_capped(world):
    """Choisir le spot du jour, qui prépare les pépites de Vany, est plafonné à 30 fois par heure."""
    world.client.cookies.set(AUTH_COOKIE_NAME, guest_token("invite-1"))
    statuses = [world.client.put("/api/step3/update_plan/1", json={"day_number": 1, "spot_id": 3}).status_code
                for _ in range(31)]
    assert statuses == [200] * 30 + [429]


def test_guest_tokens_are_capped_by_address(world):
    """Les jetons invités sont plafonnés par adresse IP : sans cela, un jeton neuf effacerait les plafonds."""
    statuses = [world.client.post("/api/auth/guest", headers={"X-Real-IP": "203.0.113.5"}).status_code
                for _ in range(11)]
    assert statuses == [200] * 10 + [429]
    assert world.client.post("/api/auth/guest", headers={"X-Real-IP": "203.0.113.6"}).status_code == 200


def request_with(cookie: str | None = None, real_ip: str | None = None) -> Request:
    """Une requête minimale, avec ou sans cookie de connexion et en-tête X-Real-IP de nginx."""
    headers = []
    if cookie:
        headers.append((b"cookie", f"{AUTH_COOKIE_NAME}={cookie}".encode()))
    if real_ip:
        headers.append((b"x-real-ip", real_ip.encode()))
    return Request({"type": "http", "headers": headers, "client": ("172.18.0.5", 50000)})


def test_calls_are_counted_per_traveller():
    """Un compte est compté à son user_id, un invité à son identifiant invité."""
    assert rate_limit.traveller_key(request_with(create_access_token({"user_id": 7, "username": "camille"}))) == "user:7"
    assert rate_limit.traveller_key(request_with(guest_token("invite-1"))) == "guest:invite-1"


def test_calls_without_token_are_counted_per_address():
    """Sans jeton valide, l'appel est compté à l'adresse transmise par nginx, sinon à celle de la connexion."""
    assert rate_limit.traveller_key(request_with(real_ip="203.0.113.5")) == "ip:203.0.113.5"
    assert rate_limit.traveller_key(request_with("pas-un-jeton")) == "ip:172.18.0.5"


def test_limits_can_be_switched_off_for_development(monkeypatch):
    """RATE_LIMIT_ENABLED=0 coupe les plafonds sur le poste de développement ; sans réglage, ils sont actifs."""
    monkeypatch.delenv("RATE_LIMIT_ENABLED", raising=False)
    assert rate_limit.rate_limit_enabled()
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "0")
    assert not rate_limit.rate_limit_enabled()
