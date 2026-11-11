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


# --- Le rafraîchissement national des prix (refresh_prices) et les corrections humaines ---

STORED = {"29810002": {"pdv_id": "29810002", "osm_element": "node/42960018", "lien_osm": "ref_osm",
                       "marque": "Système U", "name": "Station U", "latitude": 48.433395, "longitude": -4.716160}}


def _refresh(monkeypatch, state=True, dry_run=False):
    loads, marks = [], []
    monkeypatch.setattr(etl_carburants, "_read_state_file", lambda: parse_state_file(XML) if state else None)
    monkeypatch.setattr(etl_carburants, "known_stations", lambda: STORED)
    monkeypatch.setattr(etl_carburants, "load_stations", lambda rows, city: loads.append((rows, city)) or len(rows))
    monkeypatch.setattr(etl_carburants, "mark_prices_read", lambda read_at: marks.append(read_at))
    return etl_carburants.refresh_prices(dry_run=dry_run), loads, marks


def test_refresh_prices_loads_known_stations_without_a_city_and_notes_the_date(monkeypatch):
    """Le rafraîchissement relit les prix des stations déjà en base, sans commune, garde leur lien OSM et note sa date."""
    loaded, loads, marks = _refresh(monkeypatch)
    assert loaded == 1
    rows, city = loads[0]
    assert city is None
    assert (rows[0]["poi"]["name"], rows[0]["station"]["lien_osm"]) == ("Station U", "ref_osm")
    assert len(marks) == 1


def test_refresh_prices_notes_nothing_when_the_state_file_is_missing(monkeypatch):
    """Le site de l'État muet : rien n'est chargé et la date n'est pas notée, le rafraîchissement sera retenté."""
    loaded, loads, marks = _refresh(monkeypatch, state=False)
    assert (loaded, loads, marks) == (None, [], [])


def test_a_trial_refresh_notes_nothing(monkeypatch):
    """L'essai (--prix --essai) n'écrit rien : ni prix, ni date de rafraîchissement."""
    _, loads, marks = _refresh(monkeypatch, dry_run=True)
    assert (loads, marks) == ([], [])


def test_a_refresh_without_city_writes_no_city_history(monkeypatch):
    """Le rafraîchissement (ville vide) remplace les prix sans écrire d'historique de commune (histo_poi)."""
    rows, _ = _city_rows(monkeypatch, [STATION_U])
    cursor = MagicMock()
    cursor.fetchone.return_value = (12,)
    cursor.fetchall.return_value = []
    cnx = MagicMock()
    cnx.cursor.return_value = cursor
    monkeypatch.setattr(load_carburants.MySQLUtils, "connect", lambda: cnx)
    monkeypatch.setattr(load_carburants.MySQLUtils, "disconnect", lambda c: None)
    monkeypatch.setattr(load_carburants, "get_or_create_source", lambda cursor, name: 3)
    monkeypatch.setattr(load_carburants, "insert_service_and_link", lambda cursor, poi_id, service: None)
    histories = []
    monkeypatch.setattr(load_carburants, "insert_histo_poi", lambda cursor, poi_id, city: histories.append(city))
    assert load_carburants.load_stations(rows, None) == 1
    assert histories == []
    statements = [call.args[0] for call in cursor.execute.call_args_list]
    assert "DELETE FROM prix_carburants WHERE poi_id = %s" in statements
    cnx.commit.assert_called_once()


def test_a_name_corrected_by_a_human_is_never_rewritten():
    """Cas du Carrefour Contact de Plouguerneau (11 nov. 2026) : renommé à la main, il ne redevient pas « Station-service »."""
    cursor = MagicMock()
    cursor.fetchone.return_value = (48527,)
    poi = {"name": "Station-service", "latitude": 48.607, "longitude": -4.511, "address": "1 rue saint exupery"}
    assert load_carburants._upsert_poi(cursor, 3, "29880006", poi, {48527: {"name"}}) == 48527
    update = cursor.execute.call_args_list[-1].args
    assert update[0] == "UPDATE poi SET latitude = %s, longitude = %s, address = %s WHERE id = %s"
    assert update[1] == (48.607, -4.511, "1 rue saint exupery", 48527)


def test_a_new_station_is_created_with_all_its_fields():
    """Une station de l'État encore inconnue est créée, vérifiée, avec le nom et la position d'OSM."""
    cursor = MagicMock()
    cursor.fetchone.return_value = None
    cursor.lastrowid = 99
    poi = {"name": "Station U", "latitude": 48.43, "longitude": -4.71, "address": None}
    assert load_carburants._upsert_poi(cursor, 3, "29810002", poi, {}) == 99
    assert cursor.execute.call_args_list[-1].args[0].strip().startswith("INSERT INTO poi")


def test_human_fields_reads_the_columns_changed_by_live_decisions():
    """Les colonnes protégées sont celles que garde detail.avant ; masque n'en fait pas partie, load ne le touche jamais."""
    cursor = MagicMock()
    cursor.fetchall.return_value = [
        (48527, '{"file": "modifier", "avant": {"name": "Station-service"}, "champs": ["name"]}'),
        (48528, '{"file": "modifier", "avant": {"masque": 0}}'),
        (48600, '{"avant": {"latitude": 48.1, "longitude": -4.2}}'),
        (48601, "pas du json"),
    ]
    assert load_carburants.human_fields(cursor, 3) == {48527: {"name"}, 48528: set(),
                                                     48600: {"latitude", "longitude"}}
    assert "annulee_at IS NULL" in cursor.execute.call_args.args[0]
