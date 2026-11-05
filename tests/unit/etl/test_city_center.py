"""
Le centre de recherche d'une ville vient de la table `cities`, pas de son nom seul.

Cas réel : Saint-Philibert (Morbihan), créée depuis un GPX. Son nom seul, géocodé,
donne la commune homonyme de Côte-d'Or, à 600 km : 97 spots P4N y ont été récupérés.
"""
from unittest.mock import MagicMock

import pytest

from etl.extract import api_meteo, api_wikidata, scraper_p4n
from utils import geo_utils

MORBIHAN = (47.5868, -3.00045)
COTE_D_OR = (47.2062, 5.0120)


def _fake_connection(row):
    """Connexion MySQL de test : la requête renvoie `row`."""
    connection = MagicMock()
    connection.cursor.return_value.fetchone.return_value = row
    return connection


@pytest.fixture
def nominatim(monkeypatch):
    """Géocodage par le nom : renvoie volontairement la mauvaise commune."""
    geocode = MagicMock(return_value=COTE_D_OR)
    monkeypatch.setattr(geo_utils, "get_coordinates_for_city", geocode)
    return geocode


def test_city_center_uses_the_coordinates_of_the_cities_table(monkeypatch, nominatim) -> None:
    connection = _fake_connection(MORBIHAN)
    monkeypatch.setattr(geo_utils.MySQLUtils, "connect", lambda: connection)

    assert geo_utils.get_city_center("Saint-Philibert") == MORBIHAN
    nominatim.assert_not_called()
    connection.close.assert_called_once()


def test_city_center_geocodes_a_city_missing_from_the_table(monkeypatch, nominatim) -> None:
    monkeypatch.setattr(geo_utils.MySQLUtils, "connect", lambda: _fake_connection(None))

    assert geo_utils.get_city_center("Ville inconnue") == COTE_D_OR
    nominatim.assert_called_once_with("Ville inconnue")


def _wikidata_query(monkeypatch, center) -> tuple:
    """Lance l'extraction avec ce centre ; renvoie (résultat, appel HTTP simulé)."""
    monkeypatch.setattr(api_wikidata, "get_city_center", lambda city: center)
    response = MagicMock()
    response.json.return_value = {"results": {"bindings": [{"item": {}}]}}
    http_get = MagicMock(return_value=response)
    monkeypatch.setattr(api_wikidata.requests, "get", http_get)
    return api_wikidata.extract_wikidata("Saint-Philibert"), http_get


def test_wikidata_searches_around_the_coordinates_not_the_name(monkeypatch) -> None:
    data, http_get = _wikidata_query(monkeypatch, MORBIHAN)

    query = http_get.call_args.kwargs["params"]["query"]
    assert data is not None
    # Le format WKT attend la longitude d'abord : l'inverse tomberait en plein océan.
    assert '"Point(-3.00045 47.5868)"^^geo:wktLiteral' in query
    # Plus de recherche par nom : elle prenait toutes les communes homonymes.
    assert "Saint-Philibert" not in query
    assert "rdfs:label ?name" not in query


def test_wikidata_gives_up_without_coordinates(monkeypatch) -> None:
    data, http_get = _wikidata_query(monkeypatch, (None, None))

    assert data is None
    http_get.assert_not_called()


def test_p4n_searches_around_the_coordinates_of_the_city(monkeypatch) -> None:
    monkeypatch.setattr(scraper_p4n, "get_city_center", lambda city: MORBIHAN)
    driver = MagicMock()
    link = MagicMock()
    link.get_attribute.return_value = "https://park4night.com/fr/place/18293"
    driver.find_elements.return_value = [link]
    monkeypatch.setattr(scraper_p4n, "create_driver", lambda is_headless: driver)
    monkeypatch.setattr(scraper_p4n, "WebDriverWait", MagicMock())
    monkeypatch.setattr(scraper_p4n, "dismiss_cookies", lambda driver, wait: None)
    monkeypatch.setattr(scraper_p4n, "p4n_id_exists", lambda p4n_id: True)

    scraper_p4n.run_p4n_scraper("Saint-Philibert")

    search_url = driver.get.call_args_list[0].args[0]
    assert f"lat={MORBIHAN[0]}&lng={MORBIHAN[1]}" in search_url


def test_p4n_stops_without_coordinates(monkeypatch) -> None:
    monkeypatch.setattr(scraper_p4n, "get_city_center", lambda city: (None, None))
    create_driver = MagicMock()
    monkeypatch.setattr(scraper_p4n, "create_driver", create_driver)

    assert scraper_p4n.run_p4n_scraper("Ville inconnue") is None
    create_driver.assert_not_called()


@pytest.mark.parametrize("error", [scraper_p4n.TimeoutException(), RuntimeError("Chrome instance exited")])
def test_p4n_failure_returns_none_without_stopping_the_program(monkeypatch, error) -> None:
    # Cas réel : sys.exit dans le thread de l'ETL arrêtait aussi les étapes suivantes, sans message.
    monkeypatch.setattr(scraper_p4n, "get_city_center", lambda city: MORBIHAN)
    monkeypatch.setattr(scraper_p4n, "create_driver", MagicMock(side_effect=error))

    assert scraper_p4n.run_p4n_scraper("Saint-Philibert") is None


def _weather_query(monkeypatch, center, *coordinates) -> tuple:
    """Lance l'extraction météo ; renvoie (résultat, appel HTTP simulé, recherche du centre simulée)."""
    find_center = MagicMock(return_value=center)
    monkeypatch.setattr(api_meteo, "get_city_center", find_center)
    response = MagicMock()
    response.json.return_value = {"daily": {
        "time": ["2026-11-04"], "temperature_2m_max": [12], "temperature_2m_min": [5], "precipitation_sum": [0],
        "wind_speed_10m_max": [20], "weather_code": [3], "shortwave_radiation_sum": [4],
    }}
    http_get = MagicMock(return_value=response)
    monkeypatch.setattr(api_meteo.requests, "get", http_get)
    return api_meteo.extract_weather_data("Saint-Philibert", *coordinates), http_get, find_center


def test_weather_uses_the_coordinates_of_the_city_when_none_are_given(monkeypatch) -> None:
    data, http_get, _ = _weather_query(monkeypatch, MORBIHAN)

    params = http_get.call_args.kwargs["params"]
    assert (params["latitude"], params["longitude"]) == MORBIHAN
    assert data == [("2026-11-04", 12, 5, 0, 20, 3, 4)]


def test_weather_keeps_the_coordinates_it_is_given(monkeypatch) -> None:
    _, http_get, find_center = _weather_query(monkeypatch, COTE_D_OR, *MORBIHAN)

    params = http_get.call_args.kwargs["params"]
    assert (params["latitude"], params["longitude"]) == MORBIHAN
    find_center.assert_not_called()


def test_weather_gives_up_without_coordinates(monkeypatch) -> None:
    data, http_get, _ = _weather_query(monkeypatch, (None, None))

    assert data is None
    http_get.assert_not_called()
