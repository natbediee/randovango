"""
extract_osm réessaie quand Overpass est saturé ou muet.

Cas réel : Dinard, le 3 novembre 2026, 0 lieu au premier passage (502 puis délai dépassé),
puis 552 après une relance deux minutes plus tard.
"""
import json

import pytest
import requests

from etl.extract import api_osm

MORBIHAN = (47.5868, -3.00045)
ANSWER = {"elements": [{"id": 1}]}


def _response(status: int = 200, body=None, headers: dict | None = None) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response._content = (body if isinstance(body, str) else json.dumps(body or {})).encode()
    response.headers.update(headers or {})
    return response


@pytest.fixture
def overpass(monkeypatch):
    """Joue les réponses prévues, l'une après l'autre, et note les attentes au lieu de patienter."""
    class Fake:
        calls: list = []
        waits: list = []
        script: list = []

    fake = Fake()
    fake.calls, fake.waits, fake.script = [], [], []

    def post(url, data, headers, timeout):
        fake.calls.append((url, data["data"]))
        step = fake.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step

    monkeypatch.setattr(api_osm.requests, "post", post)
    monkeypatch.setattr(api_osm.time, "sleep", fake.waits.append)
    monkeypatch.setattr(api_osm, "get_city_center", lambda city: MORBIHAN)
    return fake


def test_dinard_case_succeeds_on_the_next_round(overpass) -> None:
    overpass.script = [_response(502), requests.exceptions.ReadTimeout(), _response(200, ANSWER)]

    assert api_osm.extract_osm("Dinard") == ANSWER
    assert overpass.waits == [30]


def test_waits_grow_then_gives_up(overpass) -> None:
    overpass.script = [_response(502)] * 8

    assert api_osm.extract_osm("Dinard") is None
    assert overpass.waits == [30, 60, 120]
    assert len(overpass.calls) == 8


def test_both_servers_are_tried_in_each_round(overpass) -> None:
    overpass.script = [_response(504), _response(200, ANSWER)]

    assert api_osm.extract_osm("Dinard") == ANSWER
    assert [url for url, _ in overpass.calls] == list(api_osm.OVERPASS_SERVERS)
    assert overpass.waits == []


@pytest.mark.parametrize("error", [requests.exceptions.ConnectionError(), requests.exceptions.ChunkedEncodingError()])
def test_network_errors_are_retried(overpass, error) -> None:
    overpass.script = [error, error, _response(200, ANSWER)]

    assert api_osm.extract_osm("Dinard") == ANSWER


@pytest.mark.parametrize("retry_after, expected_wait", [("90", 90), ("5", 30), ("demain", 30), ("99999", 300)])
def test_retry_after_lengthens_the_wait_but_never_shortens_it(overpass, retry_after, expected_wait) -> None:
    overpass.script = [_response(429, headers={"Retry-After": retry_after}), _response(502), _response(200, ANSWER)]

    assert api_osm.extract_osm("Dinard") == ANSWER
    assert overpass.waits == [expected_wait]


def test_error_hidden_in_a_200_is_retried_and_partial_data_dropped(overpass) -> None:
    # Overpass saturé peut répondre 200, avec une partie des lieux et une remarque d'erreur.
    partial = {"elements": [{"id": 9}], "remark": "runtime error: Query timed out in \"query\" at line 3"}
    overpass.script = [_response(200, partial), _response(502), _response(200, ANSWER)]

    assert api_osm.extract_osm("Dinard") == ANSWER


def test_unreadable_200_is_retried(overpass) -> None:
    overpass.script = [_response(200, "<html>Dispatcher too busy</html>"), _response(502), _response(200, ANSWER)]

    assert api_osm.extract_osm("Dinard") == ANSWER


def test_rejected_query_is_not_retried(overpass) -> None:
    overpass.script = [_response(400), _response(400)]

    assert api_osm.extract_osm("Dinard") is None
    assert overpass.waits == []


def test_empty_answer_is_a_success_not_a_failure(overpass) -> None:
    overpass.script = [_response(200, {"elements": []})]

    assert api_osm.extract_osm("Dinard") == {"elements": []}
    assert overpass.waits == []


def test_search_is_centered_on_the_city_coordinates(overpass) -> None:
    overpass.script = [_response(200, ANSWER)]

    api_osm.extract_osm("Saint-Philibert")

    _, query = overpass.calls[0]
    assert "47.53" in query and "-3.05" in query


def test_unknown_city_position_sends_no_query(overpass, monkeypatch) -> None:
    monkeypatch.setattr(api_osm, "get_city_center", lambda city: (None, None))

    assert api_osm.extract_osm("Nulle-Part") is None
    assert overpass.calls == []


@pytest.mark.parametrize("tag", ['"tourism"="camp_site"', '"tourism"="caravan_site"'])
def test_campings_and_motorhome_areas_are_no_longer_asked(overpass, tag) -> None:
    """Les campings et les aires de camping-car ne sont plus demandés à OSM : les spots sont la bonne source (carte #196)."""
    overpass.script = [_response(200, ANSWER)]

    api_osm.extract_osm("Plougonvelin")

    query = overpass.calls[0][1]
    assert tag not in query


def test_public_equipments_are_still_asked(overpass) -> None:
    """Les équipements publics (toilettes, douches, eau, vidange) restent demandés à OSM, seule source pour eux."""
    overpass.script = [_response(200, ANSWER)]

    api_osm.extract_osm("Plougonvelin")

    query = overpass.calls[0][1]
    for tag in ('"amenity"="toilets"', '"amenity"="shower"', '"amenity"="drinking_water"',
                '"amenity"="sanitary_dump_station"'):
        assert tag in query
