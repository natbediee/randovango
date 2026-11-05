"""Une ville sans OSM est signalée, et la suite de l'ETL continue quand même."""
import sys
from unittest.mock import MagicMock

from etl import etl_pipeline


def test_osm_failure_is_reported_and_the_next_steps_still_run(monkeypatch) -> None:
    logger, extract_wikidata = MagicMock(), MagicMock(side_effect=RuntimeError("fin du test"))
    connection = MagicMock()
    monkeypatch.setattr(etl_pipeline, "logger", logger)
    monkeypatch.setattr(etl_pipeline, "run_osm_etl", lambda city: None)
    monkeypatch.setattr(etl_pipeline, "extract_wikidata", extract_wikidata)
    monkeypatch.setattr(etl_pipeline.MySQLUtils, "connect", lambda: connection)
    monkeypatch.setattr(etl_pipeline.MySQLUtils, "disconnect", lambda conn: None)
    cursor = MagicMock()
    cursor.fetchone.return_value = (1,)  # P4N déjà scrapé : pas de Selenium ici
    monkeypatch.setattr(etl_pipeline.MySQLUtils, "get_cursor", lambda conn: cursor)
    monkeypatch.setitem(sys.modules, "services.pepite_service", MagicMock())

    etl_pipeline.scraping_background("Saint-Philibert")

    errors = [call.args[0] for call in logger.error.call_args_list]
    infos = [call.args[0] for call in logger.info.call_args_list]
    assert any("OSM en échec pour Saint-Philibert" in message for message in errors)
    assert not any("OSM chargé" in message for message in infos)
    extract_wikidata.assert_called_once_with("Saint-Philibert")
