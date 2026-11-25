"""
Compléter la ville d'une rando envoyée (etl_pipeline.complete_city, issue #316) : la météo tout de suite, puis les
chaînes de la ville demandées à la file des passages, sans fil de fond ; une erreur sur une chaîne n'arrête jamais les
autres. Ni réseau ni base : les demandes de passage sont remplacées.
"""
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


def test_a_hike_completes_its_city_without_a_background_thread(monkeypatch) -> None:
    """Une rando envoyée charge la météo, puis demande les chaînes de sa ville tout de suite, sans fil de fond (98 fils le 23 novembre 2026)."""
    order = []
    monkeypatch.setattr(etl_pipeline, "extract_weather_data", lambda city: order.append(("météo", city)) or {"jours": 1})
    monkeypatch.setattr(etl_pipeline, "load_weather_data", lambda data, city: None)
    monkeypatch.setattr(etl_pipeline, "request_city_chains", lambda city: order.append(("chaînes", city)))
    etl_pipeline.complete_city("Plougonvelin")
    assert order == [("météo", "Plougonvelin"), ("chaînes", "Plougonvelin")]
