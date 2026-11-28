"""
Une ville ne fige pas l'étape OSM de la file des passages : l'appel à Wikidata a un délai maximal. Sans réponse dans
ce délai, la ville reste sans lieux Wikidata et l'étape rend la main, pour que le passage continue.

Ni réseau ni base : l'appel HTTP, la position de la ville et la règle des doublons sont remplacés.
"""
from unittest.mock import MagicMock

import requests

from etl import etl_wikidata
from etl.extract import api_wikidata
from services import poi_duplicates_service

CONQUET_CENTER = (48.36, -4.77)


def silent_wikidata(*args, **kwargs):
    """Un Wikidata qui ne répond pas : requests lève Timeout une fois le délai passé."""
    raise requests.exceptions.ReadTimeout("Wikidata n'a pas répondu")


def test_the_wikidata_call_has_a_time_limit(monkeypatch) -> None:
    """L'appel à Wikidata donne à requests un délai de quelques secondes, jamais une attente sans fin."""
    monkeypatch.setattr(api_wikidata, "get_city_center", lambda city: CONQUET_CENTER)
    http_get = MagicMock(side_effect=silent_wikidata)
    monkeypatch.setattr(api_wikidata.requests, "get", http_get)

    api_wikidata.extract_wikidata("Le Conquet")

    assert 0 < http_get.call_args.kwargs["timeout"] <= 30


def test_a_silent_wikidata_is_asked_only_once(monkeypatch) -> None:
    """Sans réponse de Wikidata dans le délai, l'extraction rend None tout de suite, sans nouvel essai qui doublerait l'attente."""
    monkeypatch.setattr(api_wikidata, "get_city_center", lambda city: CONQUET_CENTER)
    http_get = MagicMock(side_effect=silent_wikidata)
    monkeypatch.setattr(api_wikidata.requests, "get", http_get)

    assert api_wikidata.extract_wikidata("Le Conquet") is None
    assert http_get.call_count == 1


def test_the_wikidata_step_ends_when_wikidata_is_silent(monkeypatch) -> None:
    """Wikidata muet : l'étape Wikidata d'une ville se termine sans lieu chargé, pour que le passage passe à la ville suivante."""
    monkeypatch.setattr(api_wikidata, "get_city_center", lambda city: CONQUET_CENTER)
    monkeypatch.setattr(api_wikidata.requests, "get", silent_wikidata)
    stored_places = MagicMock()
    monkeypatch.setattr(etl_wikidata, "load_wikidata_poi", stored_places)
    monkeypatch.setattr(poi_duplicates_service, "after_load", lambda city: None)

    assert etl_wikidata.run_wikidata_etl("Le Conquet") == 0
    stored_places.assert_called_once()
    assert stored_places.call_args.kwargs["df_wiki"].empty
