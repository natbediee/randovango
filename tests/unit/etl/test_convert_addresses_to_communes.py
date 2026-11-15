"""La reprise des adresses déjà en base (etl/convert_addresses_to_communes.py, issue #184, étape 2). Ni réseau ni base."""
from unittest.mock import MagicMock

import pytest

from etl import convert_addresses_to_communes as script

TREZIEN = {"id": 1, "address": "Rue de Trézien, 29810 Trézien", "latitude": 48.42, "longitude": -4.73}
PLOUARZEL = {"id": 2, "address": "2 rue du Port, 29810 Plouarzel", "latitude": 48.43, "longitude": -4.72}


@pytest.fixture(autouse=True)
def fake_conversion(monkeypatch):
    """La conversion remplacée : seul Trézien est un lieu-dit, à Plouarzel ; Lilia est en Plouguerneau."""
    def convert(address, latitude=None, longitude=None):
        return address.replace("29810 Trézien", "Trézien, 29810 Plouarzel") if address else address
    monkeypatch.setattr(script, "address_with_commune", convert)
    monkeypatch.setattr(script, "commune_of_town", lambda postcode, town, lat, lon: "Plouguerneau" if town == "Lilia" else town)
    monkeypatch.setattr(script, "human_fields", lambda cursor, poi_id: set())


def _cursor(rows):
    cursor = MagicMock()
    cursor.fetchall.return_value = [dict(row) for row in rows]
    return cursor


def _updates(cursor) -> list:
    return [call.args[1] for call in cursor.execute.call_args_list if call.args[0].startswith("UPDATE")]


def test_a_service_of_trezien_is_moved_to_plouarzel() -> None:
    """Un service de Trézien est écrit avec Plouarzel après le code postal ; celui déjà à Plouarzel n'est pas touché."""
    cursor = _cursor([TREZIEN, PLOUARZEL])
    summary = script.convert_poi_addresses(cursor, trial=False)
    assert summary["services convertis"] == 1
    assert _updates(cursor) == [("Rue de Trézien, Trézien, 29810 Plouarzel", 1, "Rue de Trézien, 29810 Trézien")]


def test_the_trial_writes_nothing() -> None:
    """À l'essai, le service de Trézien est compté et listé, mais rien n'est écrit."""
    cursor = _cursor([TREZIEN])
    assert script.convert_poi_addresses(cursor, trial=True)["services convertis"] == 1
    assert _updates(cursor) == []


def test_an_address_corrected_by_a_human_is_left_alone(monkeypatch) -> None:
    """Une adresse qu'un humain a corrigée dans la supervision n'est pas réécrite : sa décision prime."""
    monkeypatch.setattr(script, "human_fields", lambda cursor, poi_id: {"address"})
    cursor = _cursor([TREZIEN])
    summary = script.convert_poi_addresses(cursor, trial=False)
    assert summary["services laissés (adresse corrigée par un humain)"] == 1
    assert _updates(cursor) == []


def test_a_spot_of_lilia_is_labelled_plouguerneau() -> None:
    """Un spot rangé à « 29880 Lilia » prend Plouguerneau pour nom de ville."""
    spot = {"id": 9, "address": None, "city_label": "Lilia", "postal_code": "29880", "latitude": 48.62, "longitude": -4.55}
    cursor = _cursor([spot])
    assert script.convert_spots(cursor, trial=False)["spots convertis"] == 1
    assert _updates(cursor) == [(None, "Plouguerneau", 9)]


def test_a_spot_already_in_its_commune_is_left_alone() -> None:
    """Un spot déjà rangé à sa commune, sans adresse à convertir, n'est pas réécrit."""
    spot = {"id": 9, "address": "Port, 29810 Plouarzel", "city_label": "Plouarzel", "postal_code": "29810",
            "latitude": 48.43, "longitude": -4.72}
    cursor = _cursor([spot])
    assert script.convert_spots(cursor, trial=False)["spots convertis"] == 0
    assert _updates(cursor) == []
