"""
Le passage d'une ville ajoutée (etl_pipeline.scraping_background) : une ville sans OSM est signalée, une ville
ajoutée reçoit ses pharmacies FINESS (carte #241), et un échec d'une étape n'arrête jamais les suivantes.
"""
import sys
from unittest.mock import MagicMock

from etl import etl_pipeline


def _run_background(monkeypatch, city, osm=lambda city: None, pharmacies=lambda city: 0):
    """Lance scraping_background sans réseau ni base ; renvoie (logger, extract_wikidata) pour les vérifications."""
    logger, extract_wikidata = MagicMock(), MagicMock(side_effect=RuntimeError("fin du test"))
    connection = MagicMock()
    monkeypatch.setattr(etl_pipeline, "logger", logger)
    monkeypatch.setattr(etl_pipeline, "run_osm_etl", osm)
    monkeypatch.setattr(etl_pipeline, "run_fuel_etl", lambda city: 0)
    monkeypatch.setattr(etl_pipeline, "run_pharmacy_etl", pharmacies)
    monkeypatch.setattr(etl_pipeline, "extract_wikidata", extract_wikidata)
    monkeypatch.setattr(etl_pipeline.MySQLUtils, "connect", lambda: connection)
    monkeypatch.setattr(etl_pipeline.MySQLUtils, "disconnect", lambda conn: None)
    cursor = MagicMock()
    cursor.fetchone.return_value = (1,)  # P4N déjà scrapé : pas de Selenium ici
    monkeypatch.setattr(etl_pipeline.MySQLUtils, "get_cursor", lambda conn: cursor)
    monkeypatch.setitem(sys.modules, "services.pepite_service", MagicMock())
    monkeypatch.setattr(etl_pipeline, "launch_services", lambda city: None)
    etl_pipeline.scraping_background(city)
    return logger, extract_wikidata


def test_osm_failure_is_reported_and_the_next_steps_still_run(monkeypatch) -> None:
    """Saint-Philibert sans commerces ni services d'OSM : l'échec est signalé, et Wikidata passe quand même."""
    logger, extract_wikidata = _run_background(monkeypatch, "Saint-Philibert")
    errors = [call.args[0] for call in logger.error.call_args_list]
    infos = [call.args[0] for call in logger.info.call_args_list]
    assert any("OSM en échec pour Saint-Philibert" in message for message in errors)
    assert not any("OSM chargé" in message for message in infos)
    extract_wikidata.assert_called_once_with("Saint-Philibert")


def test_a_new_city_receives_its_finess_pharmacies_after_osm(monkeypatch) -> None:
    """Une ville ajoutée reçoit ses pharmacies de FINESS sans geste de l'administratrice, après OSM (leurs noms)."""
    order = []
    _run_background(monkeypatch, "Plougonvelin", osm=lambda city: order.append(("osm", city)) or 12,
                    pharmacies=lambda city: order.append(("pharmacies", city)) or 7)
    assert order == [("osm", "Plougonvelin"), ("pharmacies", "Plougonvelin")]


def test_a_finess_failure_never_stops_the_new_city(monkeypatch) -> None:
    """FINESS illisible ou en erreur : l'échec est noté, et la suite (Wikidata, P4N, pépites) passe quand même."""
    def broken(city):
        raise RuntimeError("data.gouv.fr ne répond pas")
    logger, extract_wikidata = _run_background(monkeypatch, "Plougonvelin", pharmacies=broken)
    assert any("Pharmacies ignorées pour Plougonvelin" in call.args[0] for call in logger.warning.call_args_list)
    extract_wikidata.assert_called_once_with("Plougonvelin")
    logger, extract_wikidata = _run_background(monkeypatch, "Plougonvelin", pharmacies=lambda city: None)
    assert any("Pharmacies FINESS non chargées pour Plougonvelin" in call.args[0]
               for call in logger.error.call_args_list)
    extract_wikidata.assert_called_once_with("Plougonvelin")
