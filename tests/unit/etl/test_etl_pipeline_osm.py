"""
Le passage d'une ville ajoutée (etl_pipeline.scraping_background) : OSM, les carburants, les pharmacies FINESS puis
la chaîne des spots passent comme des passages d'origine « etl » (issue #276), et un échec n'arrête jamais la suite.
"""
from unittest.mock import MagicMock

import pytest

from etl import etl_pipeline
from services import passage_service, passage_store, service_store


def _run_background(monkeypatch, city, free_chain=lambda key, city: None, spot_chain=lambda city: None,
                    passage=lambda key, city, parts=None: None):
    """Lance scraping_background sans réseau ni base."""
    monkeypatch.setattr(etl_pipeline, "logger", MagicMock())
    monkeypatch.setattr(etl_pipeline, "run_free_chain", free_chain)
    monkeypatch.setattr(etl_pipeline, "run_spot_chain", spot_chain)
    monkeypatch.setattr(etl_pipeline, "run_etl_passage", passage)
    monkeypatch.setattr(etl_pipeline, "launch_services", lambda city: None)
    etl_pipeline.scraping_background(city)


def test_a_new_city_runs_osm_then_fuel_then_finess_then_its_spots_then_its_pepites(monkeypatch) -> None:
    """Une ville ajoutée passe OSM, les carburants, FINESS (après OSM : leurs noms), les spots puis les pépites, sans geste de l'administratrice."""
    order = []
    _run_background(monkeypatch, "Plougonvelin", lambda key, city: order.append((key, city)),
                    lambda city: order.append(("spots", city)),
                    lambda key, city, parts=None: order.append((key, city)))
    assert order == [("osm", "Plougonvelin"), ("carburants", "Plougonvelin"), ("finess", "Plougonvelin"),
                     ("spots", "Plougonvelin"), ("pepites", "Plougonvelin")]


@pytest.fixture
def passages(monkeypatch):
    """Les passages simulés : `status` est l'état où run_passage laisse le passage, `asked` ce qui a été demandé."""
    state = {"status": passage_store.DONE, "asked": [], "cities": [{"id": 12, "name": "Saint-Philibert"}]}
    monkeypatch.setattr(etl_pipeline, "logger", MagicMock())
    monkeypatch.setattr(service_store, "load_cities", lambda: state["cities"])
    monkeypatch.setattr(passage_service, "create_passage",
                        lambda key, city_id, parts, origin: state["asked"].append((key, city_id, origin)
                                                                                  + ((parts,) if parts else ())) or "p1")
    monkeypatch.setattr(passage_service, "run_passage", lambda passage_id: None)
    monkeypatch.setattr(passage_store, "load_passage", lambda passage_id: {
        "status": state["status"], "error": "OpenStreetMap n'a pas répondu (Overpass muet ou en erreur)"})
    return state


def test_a_free_chain_of_the_etl_is_a_passage_of_origin_etl(passages) -> None:
    """OSM d'une ville ajoutée devient un passage d'origine « etl » sur sa ville : il se suit et se relance depuis la supervision."""
    etl_pipeline.run_free_chain("osm", "Saint-Philibert")
    assert passages["asked"] == [("osm", 12, "etl")]


def test_an_osm_failure_of_the_etl_is_written_in_the_log_with_its_reason(passages) -> None:
    """Saint-Philibert sans réponse d'OSM : l'échec, gardé en base par le passage, est aussi écrit dans le journal avec sa raison."""
    passages["status"] = passage_store.FAILED
    etl_pipeline.run_free_chain("osm", "Saint-Philibert")
    errors = [call.args[0] for call in etl_pipeline.logger.error.call_args_list]
    assert any("osm en échec pour Saint-Philibert : OpenStreetMap n'a pas répondu" in message for message in errors)


def test_a_city_missing_from_cities_launches_nothing(passages) -> None:
    """Une ville absente de la table cities ne lance aucun passage : l'erreur est écrite dans le journal."""
    passages["cities"] = []
    etl_pipeline.run_free_chain("osm", "Saint-Philibert")
    assert passages["asked"] == []
    assert etl_pipeline.logger.error.called


def test_an_error_in_a_free_chain_never_stops_the_new_city(passages, monkeypatch) -> None:
    """Une base injoignable pendant la chaîne FINESS est notée, sans lever : la ville continue ses étapes."""
    def broken(key, city_id, parts, origin):
        raise ConnectionError("base injoignable")
    monkeypatch.setattr(passage_service, "create_passage", broken)
    etl_pipeline.run_free_chain("finess", "Saint-Philibert")
    assert any("finess ignorée" in call.args[0] for call in etl_pipeline.logger.warning.call_args_list)


@pytest.mark.parametrize("already_read,parts", [
    (False, None),
    (True, ["harmonisation", "ouvertures", "verification"]),
])
def test_a_city_already_read_skips_the_source_of_the_spots(monkeypatch, already_read, parts) -> None:
    """Une ville jamais lue passe toute la chaîne des spots ; une ville déjà lue (seconde rando) ne relit pas la source, seuls ses spots encore à faire passent par les agents."""
    asked = []
    monkeypatch.setattr(etl_pipeline, "city_already_scraped", lambda city: already_read)
    monkeypatch.setattr(etl_pipeline, "run_etl_passage", lambda key, city, parts=None: asked.append((key, city, parts)))
    etl_pipeline.run_spot_chain("Guidel")
    assert asked == [("spots", "Guidel", parts)]


def test_the_spots_of_the_etl_are_a_passage_with_the_parts_asked(passages) -> None:
    """La chaîne des spots d'une ville ajoutée devient un passage d'origine « etl », avec seulement les parties demandées."""
    etl_pipeline.run_etl_passage("spots", "Saint-Philibert", ["harmonisation"])
    assert passages["asked"] == [("spots", 12, "etl", ["harmonisation"])]
