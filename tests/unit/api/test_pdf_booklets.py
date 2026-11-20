"""
Le carnet PDF d'un voyage se fabrique 3 fois au plus avec l'offre gratuite (api/routers/result.py et
services/plan_service.py, issue #263) : le premier carnet, puis deux nouvelles versions après des modifications.

Le routeur et les jetons sont les vrais ; le voyage en base, le compte des carnets et WeasyPrint sont remplacés.
"""
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import dependencies
from api.routers import result
from services import plan_service
from services.authentification import AUTH_COOKIE_NAME, create_access_token


@pytest.fixture
def world(monkeypatch):
    """Le routeur du récapitulatif ; le voyage 1, à « invite-1 », a encore world.left carnets à fabriquer."""
    state = SimpleNamespace(left=3, made=0, released=0, fail=False)

    def reserve(plan_id):
        if state.left == 0:
            return False
        state.left -= 1
        return True

    def release(plan_id):
        state.released += 1
        state.left += 1

    def make(plan):
        if state.fail:
            raise RuntimeError("WeasyPrint en panne")
        state.made += 1
        return b"%PDF-carnet"

    monkeypatch.setattr(dependencies, "get_plan_owner", lambda plan_id: {"user_id": 0, "user_token": "invite-1"})
    monkeypatch.setattr(result, "_fetch_plan_data", lambda plan_id: {"city_name": "Le Conquet", "days": []})
    monkeypatch.setattr(result, "reserve_pdf_booklet", reserve)
    monkeypatch.setattr(result, "release_pdf_booklet", release)
    monkeypatch.setattr(result, "make_pdf_booklet", make)

    app = FastAPI()
    app.include_router(result.router, prefix="/api/result")
    # raise_server_exceptions=False : une panne de fabrication répond 500, comme en vrai, au lieu d'arrêter le test.
    state.client = TestClient(app, raise_server_exceptions=False)
    state.client.cookies.set(AUTH_COOKIE_NAME, create_access_token({"guest_id": "invite-1"}))
    return state


def download(world):
    return world.client.get("/api/result/pdf?plan_id=1")


def test_three_booklets_per_trip(world):
    """Le voyageur fabrique son carnet, puis le refait deux fois après ses modifications : 3 carnets en tout."""
    statuses = [download(world).status_code for _ in range(3)]
    assert statuses == [200, 200, 200]
    assert world.made == 3


def test_fourth_booklet_is_refused_with_an_explanation(world):
    """Le 4e carnet d'un voyage est refusé (403) sans être fabriqué ; le message parle de l'offre payante à venir."""
    for _ in range(3):
        download(world)
    response = download(world)
    assert response.status_code == 403
    assert response.json() == {"detail": result.PDF_BOOKLETS_USED_MESSAGE}
    assert "offre payante" in result.PDF_BOOKLETS_USED_MESSAGE
    assert world.made == 3


def test_failed_booklet_is_not_counted(world):
    """Une fabrication en panne rend sa place : le voyageur garde ses 3 carnets."""
    world.fail = True
    assert download(world).status_code == 500
    assert world.released == 1
    assert world.left == 3


class FakeCursor:
    """Curseur MySQL de test : note chaque requête, et modifie une ligne tant que le voyage a moins de 3 carnets."""

    def __init__(self, downloads: int):
        self.downloads = downloads
        self.queries = []
        self.rowcount = 0

    def execute(self, sql, params=()):
        self.queries.append((sql, params))
        self.rowcount = 1 if self.downloads < params[1] else 0

    def close(self):
        pass


@pytest.mark.parametrize("downloads,allowed", [(0, True), (2, True), (3, False)])
def test_reservation_counts_in_one_query(monkeypatch, downloads, allowed):
    """La réservation vérifie et compte en une seule requête en base : deux demandes simultanées ne passent pas toutes les deux."""
    cursor = FakeCursor(downloads)
    connection = SimpleNamespace(cursor=lambda **kwargs: cursor, commit=lambda: None)
    monkeypatch.setattr(plan_service.MySQLUtils, "connect", lambda: connection)
    monkeypatch.setattr(plan_service.MySQLUtils, "disconnect", lambda cnx: None)
    assert plan_service.reserve_pdf_booklet(1) is allowed
    sql, params = cursor.queries[0]
    assert "pdf_downloads = pdf_downloads + 1" in sql and "pdf_downloads < %s" in sql
    assert params == (1, plan_service.MAX_FREE_PDF_BOOKLETS)
