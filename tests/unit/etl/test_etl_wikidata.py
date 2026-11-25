"""
L'étape Wikidata d'une ville (etl/etl_wikidata.py, issue #316) : elle charge les lieux et repasse la règle des doublons,
et un échec ne lève jamais. Ni réseau ni base : l'extraction, la transformation et le chargement sont remplacés.
"""
from unittest.mock import MagicMock

import pandas as pd

from etl import etl_wikidata
from services import poi_duplicates_service


def test_wikidata_loads_the_places_then_runs_the_duplicates_rule(monkeypatch):
    """Wikidata charge les lieux de la ville, puis repasse la règle des doublons (Fort Montbarey déjà venu d'OSM), et rend leur nombre."""
    loaded, rule = [], []
    monkeypatch.setattr(etl_wikidata, "extract_wikidata", lambda city: {"results": []})
    monkeypatch.setattr(etl_wikidata, "transform_wikidata", lambda wikidata_json, city_name: pd.DataFrame([{}, {}]))
    monkeypatch.setattr(etl_wikidata, "load_wikidata_poi", lambda df_wiki, city_name: loaded.append(city_name))
    monkeypatch.setattr(poi_duplicates_service, "after_load", lambda city: rule.append(city))
    assert etl_wikidata.run_wikidata_etl("Plougonvelin") == 2
    assert loaded == ["Plougonvelin"] and rule == ["Plougonvelin"]


def test_a_wikidata_failure_is_written_in_the_log_without_raising(monkeypatch):
    """Wikidata injoignable : l'échec est écrit dans le journal et rend None, sans lever, pour ne pas faire échouer OSM."""
    def unreachable(city):
        raise ConnectionError("query.wikidata.org injoignable")
    monkeypatch.setattr(etl_wikidata, "extract_wikidata", unreachable)
    monkeypatch.setattr(etl_wikidata, "logger", MagicMock())
    assert etl_wikidata.run_wikidata_etl("Plougonvelin") is None
    assert "Wikidata en échec pour Plougonvelin" in etl_wikidata.logger.error.call_args.args[0]
