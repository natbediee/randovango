"""
L'ordre du tour météo (api/routers/step1, issue #367) : les villes des voyages pas encore finis passent d'abord,
puis les plus choisies par les voyageurs, puis les autres. Ni réseau ni base : la base et l'appel météo sont remplacés.
"""
from contextlib import contextmanager
from datetime import date

import pytest

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
