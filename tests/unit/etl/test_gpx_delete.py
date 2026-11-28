"""
La suppression d'un GPX par l'admin (api/routers/etl.py, issue #384) : elle ne fait pas attendre les autres
requêtes pendant qu'elle retire la rando de MySQL et son tracé de MongoDB. Ni base ni réseau : la suppression
en base et le journal d'audit sont remplacés.
"""
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import dependencies
from api.routers import etl as etl_router

SLOW_DELETE_SECONDS = 0.5


@pytest.fixture
def slow_delete_client(monkeypatch):
    """La vraie route de suppression, pour l'admin connectée, sur des bases remplacées qui mettent une demi-seconde à répondre."""
    def delete_hike_with_trace(filename):
        time.sleep(SLOW_DELETE_SECONDS)   # une suppression bloquante, qui ne rend pas la main au serveur
        return 1, 1

    monkeypatch.setattr(etl_router, "delete_hike_with_trace", delete_hike_with_trace)
    monkeypatch.setattr(etl_router, "insert_auth_log", lambda **kwargs: None)
    app = FastAPI()
    app.include_router(etl_router.router, prefix="/api/etl")
    app.dependency_overrides[dependencies.require_admin] = lambda: {"user_id": 1, "username": "admin"}
    # « with » : un seul serveur pour toutes les requêtes du test, comme uvicorn.
    with TestClient(app) as client:
        yield client


def test_the_deletion_answers_with_what_was_removed(slow_delete_client):
    """L'admin qui supprime un GPX reçoit un succès qui dit ce qui a été retiré de MySQL et de MongoDB."""
    answer = slow_delete_client.delete("/api/etl/delete_gpx/tour.gpx").json()

    assert answer["success"] is True
    assert answer["deleted_file"] == "tour.gpx"
    assert answer["message"] == "Suppression en base : MySQL=1, MongoDB=1"


def test_two_deletions_at_the_same_time_do_not_wait_for_each_other(slow_delete_client):
    """Deux suppressions de GPX lancées ensemble sont servies ensemble : pendant l'une, le serveur répond à l'autre."""
    start = time.monotonic()
    with ThreadPoolExecutor(max_workers=2) as pool:
        names = ["tour.gpx", "boucle.gpx"]
        statuses = list(pool.map(lambda name: slow_delete_client.delete(f"/api/etl/delete_gpx/{name}").status_code, names))
    elapsed = time.monotonic() - start

    assert statuses == [200, 200]
    assert elapsed < 2 * SLOW_DELETE_SECONDS
