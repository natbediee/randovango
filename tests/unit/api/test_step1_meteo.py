"""
L'ordre du tour météo (api/routers/step1, issue #367) : les villes des voyages pas encore finis passent d'abord,
puis les plus choisies par les voyageurs, puis les autres ; la météo d'une ville choisie se redemande sans bloquer le
serveur, et sans jamais montrer d'erreur interne au navigateur. Ni réseau ni base : la base et l'appel météo sont remplacés.
"""
import inspect
from contextlib import contextmanager
from datetime import date
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routers import step1

TODAY = date(2026, 11, 28)
CONQUET, PLOUGONVELIN, BREST, MORLAIX = ({"id": i, "name": name, "latitude": 48.0, "longitude": -4.0}
                                         for i, name in enumerate(["Le Conquet", "Plougonvelin", "Brest", "Morlaix"], 1))


def trip(plan_id, city, start_date, duration_days=3):
    """Une ligne de TRIP_CITIES_QUERY : un voyage qui passe par une ville."""
    return {"plan_id": plan_id, "city_id": city["id"], "start_date": start_date, "duration_days": duration_days}


def names(cities):
    """Les noms des villes, dans l'ordre."""
    return [city["name"] for city in cities]


def test_cities_of_coming_trips_come_first():
    """La ville d'un voyage qui n'a pas encore eu lieu passe avant toutes les autres, même plus choisies par le passé."""
    trips = [trip(1, BREST, date(2026, 6, 1)), trip(2, BREST, date(2026, 7, 1)), trip(3, MORLAIX, date(2026, 12, 5))]
    ordered = step1.order_cities_for_meteo([CONQUET, PLOUGONVELIN, BREST, MORLAIX], trips, TODAY)
    assert names(ordered) == ["Morlaix", "Brest", "Le Conquet", "Plougonvelin"]


def test_a_trip_on_its_way_still_counts_as_coming():
    """Un voyage parti il y a deux jours pour trois jours n'est pas fini : sa ville passe encore en premier."""
    ordered = step1.order_cities_for_meteo([CONQUET, PLOUGONVELIN], [trip(1, PLOUGONVELIN, date(2026, 11, 26))], TODAY)
    assert names(ordered) == ["Plougonvelin", "Le Conquet"]


def test_a_finished_trip_only_counts_as_a_choice():
    """Un voyage fini la veille ne donne plus la priorité, seulement un choix de plus pour sa ville."""
    trips = [trip(1, PLOUGONVELIN, date(2026, 11, 25)), trip(2, BREST, date(2026, 10, 1)), trip(3, BREST, date(2026, 9, 1))]
    ordered = step1.order_cities_for_meteo([CONQUET, PLOUGONVELIN, BREST], trips, TODAY)
    assert names(ordered) == ["Brest", "Plougonvelin", "Le Conquet"]


def test_cities_never_chosen_keep_the_table_order():
    """Sans aucun voyage, le tour garde l'ordre de la table des villes."""
    assert names(step1.order_cities_for_meteo([CONQUET, PLOUGONVELIN, BREST], [], TODAY)) == [
        "Le Conquet", "Plougonvelin", "Brest"]


class FakeCursor:
    """Un curseur qui rend les villes, puis les villes des voyages, dans l'ordre des requêtes."""

    def __init__(self, cities, trips):
        self.answers, self.answer = [cities, trips], None

    def execute(self, query, params=None):
        self.answer = self.answers.pop(0)

    def fetchall(self):
        return self.answer


@pytest.fixture
def weather_calls(monkeypatch):
    """Les villes dont la météo est demandée, dans l'ordre ; ni attente ni appel réel."""
    calls = []
    cursor = FakeCursor([CONQUET, PLOUGONVELIN, BREST], [trip(1, BREST, date(2026, 12, 20))])

    @contextmanager
    def open_cursor(dictionary=False, buffered=False):
        yield None, cursor

    monkeypatch.setattr(step1.MySQLUtils, "open_cursor", open_cursor)
    monkeypatch.setattr(step1, "paris_today", lambda: TODAY)
    monkeypatch.setattr(step1.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(step1, "run_meteo_etl", lambda name, latitude, longitude: calls.append(name))
    return calls


def test_the_daily_refresh_starts_with_the_cities_of_travellers(weather_calls):
    """Le rafraîchissement quotidien demande d'abord la météo de Brest, ville d'un voyage de décembre, puis les autres."""
    step1.refresh_all_cities_meteo_background()
    assert weather_calls == ["Brest", "Le Conquet", "Plougonvelin"]
    assert step1.meteo_refresh_in_progress is False


def test_the_weather_of_a_chosen_city_does_not_hold_the_server():
    """La route qui redemande la météo d'une ville est une route « def » : les autres pages répondent pendant qu'elle attend Open-Meteo."""
    assert not inspect.iscoroutinefunction(step1.refresh_city_meteo)


class RefreshCursor:
    """Le curseur de refresh-meteo : la ville demandée (fetchone), puis ses prévisions (fetchall)."""

    def __init__(self, city, forecasts):
        self.city, self.forecasts = city, forecasts

    def execute(self, query, params=None):
        pass

    def fetchone(self):
        return self.city

    def fetchall(self):
        return self.forecasts


def refresh_client(monkeypatch, open_cursor):
    """La vraie route refresh-meteo, avec une base remplacée et un journal muet."""
    monkeypatch.setattr(step1.MySQLUtils, "open_cursor", open_cursor)
    monkeypatch.setattr(step1, "logger", MagicMock())
    app = FastAPI()
    app.include_router(step1.router, prefix="/api/step1")
    return TestClient(app)


def test_the_weather_answer_keeps_the_etl_result_on_the_server(monkeypatch):
    """La réponse de refresh-meteo donne les prévisions, sans le résultat de l'ETL, qui peut porter une erreur interne (issue #213)."""
    forecast = {"date": TODAY, "temp_max_c": 12, "temp_min_c": 5, "weather_code": 3, "precipitation_mm": 0,
                "wind_max_kmh": 20}

    @contextmanager
    def open_cursor(dictionary=False, buffered=False):
        yield None, RefreshCursor(PLOUGONVELIN, [forecast])

    monkeypatch.setattr(step1, "run_meteo_etl", lambda *args: {"error": "Can't connect to MySQL server on 'db'"})
    answer = refresh_client(monkeypatch, open_cursor).get("/api/step1/refresh-meteo/2").json()

    assert answer["city_name"] == "Plougonvelin" and len(answer["meteo"]) == 1
    assert "etl_result" not in answer and "MySQL" not in str(answer)


def test_a_failed_weather_refresh_does_not_show_the_internal_error(monkeypatch):
    """Une actualisation météo qui plante répond 500 avec un message simple, sans le texte de l'erreur (issue #213)."""
    @contextmanager
    def open_cursor(dictionary=False, buffered=False):
        raise RuntimeError("Access denied for user 'root'@'db_randovango'")
        yield

    response = refresh_client(monkeypatch, open_cursor).get("/api/step1/refresh-meteo/2")

    assert response.status_code == 500
    assert response.json() == {"detail": step1.METEO_REFRESH_FAILED_MESSAGE}
