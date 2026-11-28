"""
La météo d'une ville ne bloque pas un envoi : l'appel à Open-Meteo a un délai maximal. Sans réponse dans ce délai,
la rando est chargée sans météo et l'envoi passe au fichier suivant.

Ni réseau ni base : l'appel HTTP, la recherche de la commune et l'enregistrement en base sont remplacés.
"""
import shutil
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests

from etl import etl_pipeline
from etl.extract import api_meteo, gpx
from etl.transform import transform_gpx

SAMPLES = Path(__file__).parent / "gpx_samples"
CONQUET = {"name": "Le Conquet", "insee": "29040", "department": "Finistère", "region": "Bretagne"}
CONQUET_CENTER = (48.36, -4.77)


def silent_open_meteo(*args, **kwargs):
    """Un Open-Meteo qui ne répond pas : requests lève Timeout une fois le délai passé."""
    raise requests.exceptions.ReadTimeout("Open-Meteo n'a pas répondu")


def test_the_weather_call_has_a_time_limit(monkeypatch) -> None:
    """L'appel à Open-Meteo donne à requests un délai de quelques secondes, jamais une attente sans fin."""
    http_get = MagicMock(side_effect=silent_open_meteo)
    monkeypatch.setattr(api_meteo.requests, "get", http_get)

    api_meteo.extract_weather_data("Le Conquet", *CONQUET_CENTER)

    assert 0 < http_get.call_args.kwargs["timeout"] <= 30


def test_a_silent_open_meteo_gives_no_weather(monkeypatch) -> None:
    """Sans réponse d'Open-Meteo dans le délai, l'extraction rend None au lieu de lever une erreur."""
    monkeypatch.setattr(api_meteo.requests, "get", silent_open_meteo)

    assert api_meteo.extract_weather_data("Le Conquet", *CONQUET_CENTER) is None


@pytest.fixture
def waiting_dir(tmp_path, monkeypatch):
    """Un dossier d'attente vide, à la place de /usr/src/data, et aucune rando encore en base."""
    monkeypatch.setattr(gpx, "GPX_DIR", tmp_path)
    monkeypatch.setattr(gpx, "gpx_already_in_mysql", lambda fname: False)
    return tmp_path


def test_a_bulk_upload_goes_on_when_open_meteo_is_silent(waiting_dir, monkeypatch) -> None:
    """Dans un envoi en masse, deux randos de deux villes sont chargées sans météo quand Open-Meteo ne répond pas (cas craint après le fil de fond de l'envoi en masse)."""
    monkeypatch.setattr(transform_gpx, "get_commune_at", lambda lat, lon: CONQUET)
    monkeypatch.setattr(transform_gpx, "get_city_from_coordinates", lambda *args, **kwargs: "Le Conquet")
    # Le faux chargement rend une ville différente par fichier, pour que chacune demande sa météo.
    cities = iter(["Le Conquet", "Plougonvelin"])
    monkeypatch.setattr(etl_pipeline, "load_gpx_data", lambda data, gpx_path, verifie: next(cities))
    monkeypatch.setattr(api_meteo, "get_city_center", lambda city: CONQUET_CENTER)
    monkeypatch.setattr(api_meteo.requests, "get", silent_open_meteo)
    stored_weather = MagicMock()
    monkeypatch.setattr(etl_pipeline, "load_weather_data", stored_weather)
    monkeypatch.setattr(etl_pipeline, "request_chains_of_cities", lambda cities: None)
    for name in ("trace_1.gpx", "trace_2.gpx"):
        shutil.copy(SAMPLES / "trace.gpx", waiting_dir / name)

    outcomes = etl_pipeline.process_waiting_folder(user_role="admin")

    assert [(o["city"], o["reason"]) for o in outcomes] == [("Le Conquet", None), ("Plougonvelin", None)]
    stored_weather.assert_not_called()
