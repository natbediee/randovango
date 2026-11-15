"""
Les noms venus de l'extérieur sont convertis en commune dès leur arrivée en base (issue #184, étape 2) : adresses
des agents, d'OSM, de FINESS et de l'État pour les carburants, nom de ville des spots. Ni réseau ni base.
"""
from unittest.mock import MagicMock

import pytest

from etl.load import load_carburants, load_p4n, load_pharmacies
from services import service_store
from utils import geo_utils


@pytest.fixture
def plouarzel_postcode(monkeypatch):
    """Le 29810 et ses quatre communes ; le point de Trézien est en Plouarzel."""
    monkeypatch.setattr(geo_utils, "communes_of_postcode",
                        lambda postcode: ["Brélès", "Lampaul-Plouarzel", "Plouarzel", "Ploumoguer"]
                        if postcode == "29810" else [])
    monkeypatch.setattr(geo_utils, "get_commune_from_coordinates", lambda lat, lon: ("Plouarzel", "29177"))


def test_an_agent_address_is_stored_with_its_commune(plouarzel_postcode) -> None:
    """L'adresse d'un service trouvé par un agent à Trézien est écrite avec Plouarzel après le code postal."""
    row = {"nom": "Le Cabestan", "adresse": "Rue de Trézien, 29810 Trézien"}
    assert service_store.stored_address(row, (48.42, -4.73)) == "Rue de Trézien, Trézien, 29810 Plouarzel"


def test_an_agent_address_without_position_is_left_alone(plouarzel_postcode) -> None:
    """Sans position, le 29810 a quatre communes : l'adresse de l'agent est écrite telle quelle."""
    assert service_store.stored_address({"adresse": "Rue de Trézien, 29810 Trézien"}, None) == "Rue de Trézien, 29810 Trézien"


@pytest.mark.parametrize("module", [load_pharmacies, load_carburants])
def test_a_state_service_is_created_with_its_commune(module, plouarzel_postcode) -> None:
    """Une pharmacie de FINESS ou une station de l'État, à Trézien, est créée avec Plouarzel après le code postal."""
    cursor = MagicMock()
    cursor.fetchone.return_value = None
    poi = {"name": "Pharmacie de Trézien", "latitude": 48.42, "longitude": -4.73, "address": "Bourg, 29810 TREZIEN"}
    module._upsert_poi(cursor, 7, "290000001", poi, {})
    inserted = cursor.execute.call_args.args[1]
    assert "Bourg, TREZIEN, 29810 Plouarzel" in inserted


def test_a_spot_of_a_locality_is_labelled_with_its_commune(monkeypatch) -> None:
    """Un spot que la source des spots range à « 29880 Lilia » est rangé à Plouguerneau."""
    monkeypatch.setattr(load_p4n, "commune_of_town", lambda postcode, label, lat, lon: "Plouguerneau")
    row = {"postal_code": "29880", "city_label": "Lilia", "latitude": 48.62, "longitude": -4.55}
    assert load_p4n.commune_label(row) == "Plouguerneau"


def test_a_spot_label_is_kept_when_the_commune_is_unknown(monkeypatch) -> None:
    """Sans code postal, ou sans réponse de l'État, le nom de ville reçu pour un spot est gardé."""
    monkeypatch.setattr(load_p4n, "commune_of_town", lambda postcode, label, lat, lon: None)
    assert load_p4n.commune_label({"postal_code": "29880", "city_label": "Lilia"}) == "Lilia"
    assert load_p4n.commune_label({"postal_code": None, "city_label": "Lilia"}) == "Lilia"
    assert load_p4n.commune_label({"postal_code": "29880", "city_label": None}) is None
