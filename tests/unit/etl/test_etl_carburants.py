"""
Les cas importants de la règle des carburants, sur une ville entière (etl_carburants.city_rows) et au chargement :
la station de l'État est prouvée, la station seulement dans OSM est masquée, un prix absent reste vide,
chaque carburant a sa ligne.
"""
from unittest.mock import MagicMock

from etl import etl_carburants
from etl.load import load_carburants
from etl.transform.transform_carburants import parse_state_file

# Une station de l'État à Plouarzel, qui vend trois carburants, dont un sans prix (rupture définitive).
XML = """<?xml version="1.0" encoding="ISO-8859-1" standalone="yes"?>
<pdv_liste>
  <pdv id="29810002" latitude="4843200" longitude="-472100" cp="29810" pop="R">
    <adresse>RUE DE BREST</adresse>
    <ville>PLOUARZEL</ville>
    <prix nom="Gazole" id="1" maj="2026-11-07 08:00:00" valeur="1.689"/>
    <prix nom="E10" id="5" maj="2026-11-07 08:00:00" valeur="1.799"/>
    <rupture nom="GPLc" id="4" debut="2017-09-27 11:38:49" fin="" type="definitive"/>
  </pdv>
</pdv_liste>""".encode("iso-8859-1")

STATION_U = {"type": "node", "id": 42960018, "lat": 48.433395, "lon": -4.716160,
             "tags": {"amenity": "fuel", "ref:FR:prix-carburants": "29810002", "name": "Station U",
                      "brand": "Système U"}}
# Le Total de Portsall : connu d'OSM, absent du fichier de l'État.
TOTAL_PORTSALL = {"type": "way", "id": 7, "center": {"lat": 48.4300, "lon": -4.7050},
                  "tags": {"amenity": "fuel", "name": "Total", "brand": "TotalEnergies"}}


def _city_rows(monkeypatch, elements):
    monkeypatch.setattr(etl_carburants, "get_city_center", lambda city: (48.4300, -4.7200))
    monkeypatch.setattr(etl_carburants, "extract_osm_fuel", lambda *args: elements)
    return etl_carburants.city_rows("Plouarzel", parse_state_file(XML))


def test_a_state_station_is_loaded_with_its_osm_name(monkeypatch):
    rows, osm_only = _city_rows(monkeypatch, [STATION_U])
    assert len(rows) == 1
    assert rows[0]["poi"]["name"] == "Station U"
    assert rows[0]["station"]["lien_osm"] == "ref_osm"
    assert osm_only == []


def test_a_station_only_in_osm_is_never_loaded(monkeypatch):
    """Cas de Portsall : la station OSM seule est comptée à part, aucune ligne n'est faite pour elle."""
    rows, osm_only = _city_rows(monkeypatch, [STATION_U, TOTAL_PORTSALL])
    assert [row["station"]["pdv_id"] for row in rows] == ["29810002"]
    assert [osm["osm_element"] for osm in osm_only] == ["way/7"]


def test_a_state_station_without_osm_is_still_loaded(monkeypatch):
    """Le fichier de l'État suffit à prouver la station : sans OSM, elle est gardée sous le nom générique."""
    rows, osm_only = _city_rows(monkeypatch, [])
    assert len(rows) == 1
    assert (rows[0]["station"]["lien_osm"], rows[0]["station"]["marque"]) == ("aucun", None)


def test_nothing_is_loaded_when_overpass_does_not_answer(monkeypatch):
    assert _city_rows(monkeypatch, None) is None


def test_each_fuel_has_its_line_and_a_missing_price_stays_empty(monkeypatch):
    rows, _ = _city_rows(monkeypatch, [STATION_U])
    prices = {price["carburant"]: price for price in rows[0]["prix"]}
    assert sorted(prices) == ["E10", "GPLc", "Gazole"]
    assert (prices["Gazole"]["prix"], prices["E10"]["prix"]) == (1.689, 1.799)
    assert prices["GPLc"]["prix"] is None
    assert prices["GPLc"]["rupture_type"] == "definitive"


def test_prices_are_replaced_as_a_block_with_null_for_a_missing_price(monkeypatch):
    rows, _ = _city_rows(monkeypatch, [STATION_U])
    cursor = MagicMock()
    load_carburants._replace_prices(cursor, 12, rows[0]["prix"])
    calls = cursor.execute.call_args_list
    assert calls[0].args == ("DELETE FROM prix_carburants WHERE poi_id = %s", (12,))
    inserted = {call.args[1][1]: call.args[1][2] for call in calls[1:]}
    assert inserted == {"E10": 1.799, "GPLc": None, "Gazole": 1.689}
