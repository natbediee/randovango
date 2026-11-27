"""
Compléter les villes d'un envoi (etl_pipeline.complete_cities, issues #316 et #328) : la météo tout de suite, une fois
par ville, puis les chaînes de chaque ville demandées à la file des passages, par un seul fil qui ne retient pas la
réponse ; une erreur sur une chaîne ou une ville n'arrête jamais les autres. Ni réseau ni base : les demandes de
passage et la météo sont remplacés.
"""
import threading
from unittest.mock import MagicMock

import pytest

from etl import etl_pipeline
from services import passage_queue, passage_service


@pytest.fixture
def asked(monkeypatch):
    """Ce que l'ETL demande à la file, dans l'ordre : les chaînes de la ville, les services, puis le réveil de la file."""
    calls = []
    monkeypatch.setattr(etl_pipeline, "logger", MagicMock())
    monkeypatch.setattr(passage_service, "request_city_chain", lambda key, city: calls.append((key, city)) or "p1")
    monkeypatch.setattr(passage_service, "request_etl_passage", lambda city: calls.append(("services", city)) or None)
    monkeypatch.setattr(passage_queue, "wake", lambda: calls.append(("réveil",)))
    return calls


def test_a_new_city_asks_each_of_its_chains_then_wakes_the_queue(asked) -> None:
    """Une ville ajoutée demande OSM, carburants, FINESS, spots, pépites et services à la file, puis la réveille, sans geste de l'administratrice."""
    etl_pipeline.request_city_chains("Plougonvelin")
    assert asked == [("osm", "Plougonvelin"), ("carburants", "Plougonvelin"), ("finess", "Plougonvelin"),
                     ("spots", "Plougonvelin"), ("pepites", "Plougonvelin"), ("services", "Plougonvelin"),
                     ("réveil",)]


def test_an_error_on_one_chain_never_stops_the_others(asked, monkeypatch) -> None:
    """Une base injoignable en demandant FINESS est notée dans le journal ; les spots, les pépites et les services sont quand même demandés."""
    def broken_on_finess(key, city):
        if key == "finess":
            raise ConnectionError("base injoignable")
        asked.append((key, city))
    monkeypatch.setattr(passage_service, "request_city_chain", broken_on_finess)
    etl_pipeline.request_city_chains("Saint-Philibert")
    assert ("spots", "Saint-Philibert") in asked and ("services", "Saint-Philibert") in asked
    assert any("finess non demandée pour Saint-Philibert" in call.args[0]
               for call in etl_pipeline.logger.warning.call_args_list)


def test_an_upload_answers_before_the_chains_are_asked(monkeypatch) -> None:
    """Le cas du 25 novembre 2026 : l'envoi rend la main après la météo, sans attendre la demande des chaînes (≈ 1 s par ville), qui se fait à côté."""
    may_ask = threading.Event()
    asked = []

    def slow_request(city):
        may_ask.wait(5)
        asked.append(city)
    monkeypatch.setattr(etl_pipeline, "load_weather", lambda city: None)
    monkeypatch.setattr(etl_pipeline, "request_city_chains", slow_request)

    worker = etl_pipeline.complete_cities(["Plougonvelin"])

    assert asked == []
    may_ask.set()
    worker.join(5)
    assert asked == ["Plougonvelin"]


def test_each_city_gets_its_weather_once_then_its_chains(monkeypatch) -> None:
    """Trois randos sur deux villes : chaque ville reçoit sa météo une fois, puis ses chaînes une fois, Le Conquet avant Plouarzel comme à l'arrivée."""
    weather, chains = [], []
    monkeypatch.setattr(etl_pipeline, "load_weather", weather.append)
    monkeypatch.setattr(etl_pipeline, "request_city_chains", chains.append)
    outcomes = [{"filename": "a.gpx", "city": "Le Conquet", "reason": None},
                {"filename": "b.gpx", "city": None, "reason": "le fichier ne contient aucune trace"},
                {"filename": "c.gpx", "city": "Plouarzel", "reason": None},
                {"filename": "d.gpx", "city": "Le Conquet", "reason": None}]

    etl_pipeline.complete_cities(etl_pipeline.loaded_cities(outcomes)).join(5)

    assert sorted(weather) == ["Le Conquet", "Plouarzel"]
    assert chains == ["Le Conquet", "Plouarzel"]


def test_an_error_on_one_city_never_stops_the_next_ones(monkeypatch) -> None:
    """Une ville dont la demande échoue (base injoignable) est notée dans le journal ; la ville suivante est quand même demandée."""
    monkeypatch.setattr(etl_pipeline, "logger", MagicMock())
    asked = []

    def broken_on_crozon(city):
        if city == "Crozon":
            raise ConnectionError("base injoignable")
        asked.append(city)
    monkeypatch.setattr(etl_pipeline, "request_city_chains", broken_on_crozon)

    etl_pipeline.request_chains_of_cities(["Crozon", "Camaret-sur-Mer"])

    assert asked == ["Camaret-sur-Mer"]
    assert any("Chaînes non demandées pour Crozon" in call.args[0]
               for call in etl_pipeline.logger.warning.call_args_list)


def test_two_uploads_never_ask_their_chains_at_the_same_time(monkeypatch) -> None:
    """Deux envois qui se suivent demandent leurs chaînes l'un après l'autre : sinon tous deux pourraient croire Crozon pas encore demandée."""
    inside, overlaps = [], []

    def request(city):
        if inside:
            overlaps.append(city)
        inside.append(city)
        threading.Event().wait(0.05)
        inside.remove(city)
    monkeypatch.setattr(etl_pipeline, "request_city_chains", request)

    workers = [etl_pipeline.start_chain_requests(["Crozon"]), etl_pipeline.start_chain_requests(["Crozon"])]
    for worker in workers:
        worker.join(5)

    assert overlaps == []
