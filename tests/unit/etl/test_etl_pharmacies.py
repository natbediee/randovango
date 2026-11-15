"""
Les pharmacies de FINESS sur une ville entière (etl_pharmacies.city_rows) et au chargement : seules les pharmacies
ouvertes et proches sont chargées, une pharmacie fermée est masquée, une correction humaine n'est jamais réécrite.
"""
from datetime import date
from unittest.mock import MagicMock

from etl import etl_pharmacies
from etl.load import load_pharmacies


def _pharmacy(finess, name, latitude, longitude, etat="A", fermeture=None, postcode="29217"):
    return {"finess": finess, "nom_finess": name, "address": "Rue, 29217 Plougonvelin", "code_postal": postcode,
            "latitude": latitude, "longitude": longitude, "etat": etat, "fermeture": fermeture}


RIVOALEN = _pharmacy("290011048", "PHARMACIE RIVOALEN-COUSIN", 48.341576, -4.719367)
# Fermée le 31 octobre 2026, comme la Pharmacie Fresneau de Kérinou à Brest.
CLOSED = _pharmacy("290013226", "PHARMACIE FRESNEAU", 48.3420, -4.7190, etat="I", fermeture=date(2026, 10, 31))
# Une pharmacie de Quimper, bien au-delà des 5 km de Plougonvelin.
FAR = _pharmacy("290000001", "PHARMACIE DE LA GARE", 47.9950, -4.1020, postcode="29000")
# Une pharmacie de Plougonvelin hors de la zone de 5 km : son code postal est touché, elle est chargée aussi.
SAME_POSTCODE = _pharmacy("290000002", "PHARMACIE DU TREZ HIR", 48.4200, -4.7200)
# Une pharmacie d'outre-mer sans position.
NO_POSITION = _pharmacy("970000001", "PHARMACIE DU PORT", None, None)


def _city_rows(monkeypatch, pharmacies):
    monkeypatch.setattr(etl_pharmacies, "get_city_center", lambda city: (48.3400, -4.7200))
    monkeypatch.setattr(etl_pharmacies, "osm_pharmacies_near", lambda *args: [])
    return etl_pharmacies.city_rows("Plougonvelin", pharmacies, date(2026, 11, 14))


def test_only_open_and_nearby_pharmacies_are_loaded(monkeypatch):
    """Plougonvelin : la Rivoalen-Cousin est chargée ; ni la fermée, ni celle de Quimper, ni celle sans position."""
    rows = _city_rows(monkeypatch, [RIVOALEN, CLOSED, FAR, NO_POSITION])
    assert [row["finess"] for row in rows] == ["290011048"]
    assert rows[0]["poi"]["name"] == "Pharmacie Rivoalen-Cousin"


def test_every_pharmacy_of_a_postcode_in_the_zone_is_loaded(monkeypatch):
    """Brest : 20 des 33 pharmacies dans la zone. Un code postal touché est chargé en entier, sinon l'étape 4 cacherait
    des pharmacies d'OSM dont la pharmacie FINESS manque."""
    rows = _city_rows(monkeypatch, [RIVOALEN, SAME_POSTCODE, FAR])
    assert sorted(row["finess"] for row in rows) == ["290000002", "290011048"]


def test_a_city_missing_from_the_table_loads_nothing(monkeypatch):
    """Une ville absente de la table cities : rien n'est chargé, le passage le dit."""
    monkeypatch.setattr(etl_pharmacies, "get_city_center", lambda city: (None, None))
    assert etl_pharmacies.city_rows("Nulle-Part", [RIVOALEN], date(2026, 11, 14)) is None


def _connection(monkeypatch, cursor):
    cnx = MagicMock()
    cnx.cursor.return_value = cursor
    monkeypatch.setattr(load_pharmacies.MySQLUtils, "connect", lambda: cnx)
    monkeypatch.setattr(load_pharmacies.MySQLUtils, "disconnect", lambda c: None)
    return cnx


def test_a_pharmacy_is_loaded_as_a_pharmacy_of_the_finess_source(monkeypatch):
    """Une pharmacie devient un service « pharmacy » de la source finess, rattaché à sa ville, son numéro FINESS gardé."""
    rows = _city_rows(monkeypatch, [RIVOALEN])
    cursor = MagicMock()
    cursor.fetchone.return_value = None
    cursor.fetchall.return_value = []
    cursor.lastrowid = 90
    cnx = _connection(monkeypatch, cursor)
    sources, services, histories = [], [], []
    monkeypatch.setattr(load_pharmacies, "get_or_create_source", lambda cur, name: sources.append(name) or 7)
    monkeypatch.setattr(load_pharmacies, "insert_service_and_link", lambda cur, poi_id, s: services.append((poi_id, s)))
    monkeypatch.setattr(load_pharmacies, "insert_histo_poi", lambda cur, poi_id, city: histories.append((poi_id, city)))
    assert load_pharmacies.load_pharmacy_rows(rows, "Plougonvelin") == 1
    assert sources == ["finess"]
    assert services == [(90, "pharmacy")]
    assert histories == [(90, "Plougonvelin")]
    insert = cursor.execute.call_args_list[-1].args
    assert insert[0].strip().startswith("INSERT INTO poi") and insert[1][0] == "290011048"
    cnx.commit.assert_called_once()


def test_a_name_corrected_by_a_human_is_never_rewritten():
    """Un nom corrigé dans /supervision reste : le passage suivant ne remet que l'adresse et la position."""
    cursor = MagicMock()
    cursor.fetchone.return_value = (90,)
    poi = {"name": "Pharmacie Rivoalen-Cousin", "latitude": 48.34, "longitude": -4.72, "address": "Place, 29217 Plougonvelin"}
    assert load_pharmacies._upsert_poi(cursor, 7, "290011048", poi, {90: {"name"}}) == 90
    update = cursor.execute.call_args_list[-1].args
    assert update[0] == "UPDATE poi SET latitude = %s, longitude = %s, address = %s WHERE id = %s"


def test_a_closed_pharmacy_is_hidden(monkeypatch):
    """La Pharmacie Fresneau de Kérinou, fermée le 31 octobre 2026 : son service est masqué."""
    cursor = MagicMock()
    cursor.rowcount = 1
    cnx = _connection(monkeypatch, cursor)
    assert load_pharmacies.hide_closed({"290013226": date(2026, 10, 31)}, {"290013226": 55}) == 1
    calls = [call.args for call in cursor.execute.call_args_list]
    assert calls == [("UPDATE poi SET masque = 1 WHERE id = %s AND masque = 0", (55,))]
    cnx.commit.assert_called_once()


def test_a_trial_run_writes_nothing(monkeypatch):
    """L'essai (--essai) affiche ce qui serait chargé et masqué, sans rien écrire."""
    writes = []
    monkeypatch.setattr(etl_pharmacies, "get_city_center", lambda city: (48.3400, -4.7200))
    monkeypatch.setattr(etl_pharmacies, "osm_pharmacies_near", lambda *args: [])
    monkeypatch.setattr(etl_pharmacies, "load_pharmacy_rows", lambda rows, city: writes.append(rows))
    monkeypatch.setattr(etl_pharmacies, "hide_closed", lambda closed, known: writes.append(closed))
    monkeypatch.setattr(etl_pharmacies, "known_pharmacies", lambda: {"290013226": 55})
    assert etl_pharmacies.run_city_etl("Plougonvelin", [RIVOALEN, CLOSED], dry_run=True) == 1
    assert etl_pharmacies.hide_closed_pharmacies([RIVOALEN, CLOSED], dry_run=True) == 1
    assert writes == []


def test_a_new_city_reads_finess_then_loads_its_pharmacies(monkeypatch):
    """Une ville ajoutée : FINESS est lu, puis ses pharmacies sont chargées ; sans fichier, rien n'est écrit."""
    loaded = []
    monkeypatch.setattr(etl_pharmacies, "read_pharmacies", lambda: [RIVOALEN])
    monkeypatch.setattr(etl_pharmacies, "run_city_etl", lambda city, pharmacies: loaded.append((city, pharmacies)) or 1)
    assert etl_pharmacies.run_new_city_etl("Plougonvelin") == 1
    assert loaded == [("Plougonvelin", [RIVOALEN])]
    monkeypatch.setattr(etl_pharmacies, "read_pharmacies", lambda: None)
    assert etl_pharmacies.run_new_city_etl("Plougonvelin") is None
    assert len(loaded) == 1


def _row_in(town):
    return {"poi": {"address": f"Rue, 29217 {town}"}}


def test_the_report_counts_the_pharmacies_of_the_commune_apart():
    """Plougonvelin n'a qu'une pharmacie : les 6 autres de la zone sont comptées « autour », commune par commune."""
    rows = [_row_in("Plougonvelin"), _row_in("Le Conquet"), _row_in("Plouzane"), _row_in("Plouzané")]
    assert etl_pharmacies.towns_summary("Plougonvelin", rows) == (
        "Plougonvelin : 1 pharmacie dans la commune, 3 autour (Le Conquet 1, Plouzane 2)")
