"""
Le carburant retenu dans l'onglet Carburant de l'étape 4 (carte #188) : GET et PUT /api/step4/fuel_choice.

La route, le service et les jetons sont les vrais ; seule la table fuel_choices est remplacée par un dictionnaire
{(user_id, user_token): fuel}, lu et écrit par un faux curseur MySQL.
"""
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routers import step4
from services import fuel_choice_service
from services.authentification import AUTH_COOKIE_NAME, create_access_token


class FakeCursor:
    """Faux curseur : SELECT lit la ligne du voyageur dans rows, INSERT … ON DUPLICATE KEY la remplace."""

    def __init__(self, rows: dict):
        self.rows = rows
        self.found = None

    def execute(self, sql, params=()):
        if sql.strip().startswith("SELECT"):
            key = tuple(params)
            self.found = {"fuel": self.rows[key]} if key in self.rows else None
        elif sql.strip().startswith("INSERT INTO fuel_choices"):
            user_id, user_token, fuel, _chosen_at = params
            self.rows[(user_id, user_token)] = fuel

    def fetchone(self):
        return self.found

    def close(self):
        pass


@pytest.fixture
def table(monkeypatch):
    """La table fuel_choices en mémoire : un dictionnaire {(user_id, user_token): fuel}."""
    rows = {}
    connection = SimpleNamespace(cursor=lambda dictionary=False: FakeCursor(rows), commit=lambda: None)
    monkeypatch.setattr(fuel_choice_service.MySQLUtils, "connect", staticmethod(lambda: connection))
    monkeypatch.setattr(fuel_choice_service.MySQLUtils, "disconnect", staticmethod(lambda cnx: None))
    return rows


@pytest.fixture
def client():
    """Un client de l'API qui n'a que le routeur de l'étape 4, branché comme dans main.py."""
    app = FastAPI()
    app.include_router(step4.router, prefix="/api/step4")
    return TestClient(app)


def account_cookie(user_id: int, username: str) -> dict:
    """Le cookie d'un compte qui vient de se connecter : un nouveau jeton à chaque appel."""
    token = create_access_token({"user_id": user_id, "username": username}, timedelta(minutes=60))
    return {AUTH_COOKIE_NAME: token}


def guest_cookie(guest_id: str) -> dict:
    """Le cookie d'un invité, avec son identifiant invité."""
    return {AUTH_COOKIE_NAME: create_access_token({"guest_id": guest_id}, timedelta(days=30))}


def read_fuel(client, cookies) -> str | None:
    """Le carburant sur lequel l'onglet se rouvre pour ce voyageur."""
    client.cookies.clear()
    response = client.get("/api/step4/fuel_choice", cookies=cookies)
    assert response.status_code == 200
    return response.json()["fuel"]


def choose_fuel(client, cookies, fuel):
    """Le voyageur clique sur un carburant (ou « Tout », None) dans l'onglet Carburant."""
    client.cookies.clear()
    return client.put("/api/step4/fuel_choice", json={"fuel": fuel}, cookies=cookies)


def test_first_visit_opens_on_all_fuels(table, client):
    """Un voyageur qui n'a encore choisi aucun carburant voit l'onglet s'ouvrir sur « Tout » (None)."""
    assert read_fuel(client, guest_cookie("invite-1")) is None


def test_chosen_fuel_is_kept(table, client):
    """Le carburant choisi (SP95-E10) est retenu : l'onglet se rouvre dessus au retour du voyageur."""
    cookies = guest_cookie("invite-1")
    assert choose_fuel(client, cookies, "E10").status_code == 200
    assert read_fuel(client, cookies) == "E10"


def test_all_fuels_is_kept(table, client):
    """« Tout » choisi après un autre carburant est retenu (None) : l'onglet ne se rouvre plus sur l'ancien choix."""
    cookies = guest_cookie("invite-1")
    choose_fuel(client, cookies, "E10")
    choose_fuel(client, cookies, None)
    assert read_fuel(client, cookies) is None


def test_new_choice_replaces_the_previous_one(table, client):
    """Un nouveau choix remplace l'ancien : le voyageur garde une seule ligne dans fuel_choices."""
    cookies = account_cookie(7, "camille")
    choose_fuel(client, cookies, "E10")
    choose_fuel(client, cookies, "GPLc")
    assert table == {(7, ""): "GPLc"}


def test_account_finds_its_fuel_after_logging_in_again(table, client):
    """Un compte retrouve son carburant avec un nouveau jeton : le choix est rangé sur son user_id, pas sur le jeton."""
    choose_fuel(client, account_cookie(7, "camille"), "SP98")
    assert read_fuel(client, account_cookie(7, "camille")) == "SP98"


def test_choice_is_stored_like_trips(table, client):
    """Le choix se range comme les voyages : un compte sur (user_id, ''), un invité sur (0, son identifiant invité)."""
    choose_fuel(client, account_cookie(7, "camille"), "E10")
    choose_fuel(client, guest_cookie("invite-1"), "GPLc")
    assert table == {(7, ""): "E10", (0, "invite-1"): "GPLc"}


def test_account_does_not_read_another_account_choice(table, client):
    """Un compte ne lit pas le carburant d'un autre compte : il voit « Tout », comme sans choix."""
    choose_fuel(client, account_cookie(7, "camille"), "E10")
    assert read_fuel(client, account_cookie(8, "louis")) is None


def test_guest_does_not_read_another_guest_choice(table, client):
    """Un invité ne lit pas le carburant d'un autre invité, ni celui d'un compte."""
    choose_fuel(client, guest_cookie("invite-1"), "E10")
    choose_fuel(client, account_cookie(7, "camille"), "SP98")
    assert read_fuel(client, guest_cookie("invite-2")) is None


def test_unknown_fuel_is_refused(table, client):
    """Un carburant inconnu est refusé (422) et rien n'est enregistré."""
    response = choose_fuel(client, guest_cookie("invite-1"), "Kérosène")
    assert response.status_code == 422
    assert table == {}


def test_without_token_the_choice_is_refused(table, client):
    """Sans jeton, la lecture comme l'enregistrement du carburant sont refusés (401)."""
    client.cookies.clear()
    assert client.get("/api/step4/fuel_choice").status_code == 401
    assert client.put("/api/step4/fuel_choice", json={"fuel": "E10"}).status_code == 401
