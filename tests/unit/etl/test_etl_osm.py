"""L'étape OSM d'une ville, et le fichier des villes à rattraper."""
import json
from unittest.mock import MagicMock

import pandas as pd
import pytest

from etl import etl_osm


@pytest.fixture
def steps(monkeypatch, tmp_path):
    fake = MagicMock()
    fake.extract.return_value = {"elements": [{"id": 1}]}
    fake.transform.return_value = pd.DataFrame([{"osm_id": 1}, {"osm_id": 2}])
    monkeypatch.setattr(etl_osm, "extract_osm", fake.extract)
    monkeypatch.setattr(etl_osm, "transform_osm", fake.transform)
    monkeypatch.setattr(etl_osm, "load_osm_poi", fake.load)
    monkeypatch.setattr(etl_osm, "CATCH_UP_FILE", tmp_path / "osm_a_rattraper.json")
    return fake


def _catch_up_file() -> dict:
    return json.loads(etl_osm.CATCH_UP_FILE.read_text(encoding="utf-8"))


def test_success_returns_the_number_of_places(steps) -> None:
    assert etl_osm.run_osm_etl("Dinard") == 2
    steps.load.assert_called_once()
    assert _catch_up_file() == {}


def test_failure_is_written_to_the_file_and_nothing_is_loaded(steps) -> None:
    steps.extract.return_value = None

    assert etl_osm.run_osm_etl("Dinard") is None
    steps.transform.assert_not_called()
    steps.load.assert_not_called()
    assert list(_catch_up_file()) == ["Dinard"]
    assert _catch_up_file()["Dinard"]["etat"] == "echec"


def test_city_is_noted_before_the_extraction_in_case_the_thread_is_cut(steps) -> None:
    # uvicorn --reload coupe le thread sans prévenir : la ville doit déjà être notée.
    seen = {}

    def extract(city):
        seen.update(_catch_up_file())
        return {"elements": []}

    steps.extract.side_effect = extract

    etl_osm.run_osm_etl("Dinard")

    assert seen["Dinard"]["etat"] == "en_cours"
    assert _catch_up_file() == {}


def test_loading_error_keeps_the_city_in_the_file(steps) -> None:
    steps.load.side_effect = RuntimeError("MySQL indisponible")

    with pytest.raises(RuntimeError):
        etl_osm.run_osm_etl("Dinard")

    assert _catch_up_file()["Dinard"]["etat"] == "echec"


def test_a_successful_retry_removes_only_that_city(steps) -> None:
    steps.extract.return_value = None
    etl_osm.run_osm_etl("Dinard")
    etl_osm.run_osm_etl("Saint-Philibert")

    steps.extract.return_value = {"elements": [{"id": 1}]}
    etl_osm.run_osm_etl("Dinard")

    assert list(_catch_up_file()) == ["Saint-Philibert"]


def test_damaged_file_does_not_block_the_city(steps) -> None:
    etl_osm.CATCH_UP_FILE.write_text("{ pas du json", encoding="utf-8")

    assert etl_osm.run_osm_etl("Dinard") == 2
    assert _catch_up_file() == {}
