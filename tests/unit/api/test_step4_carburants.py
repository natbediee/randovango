"""L'onglet carburant de l'étape 4 : l'État est la référence, une station sans données de l'État n'est pas montrée."""
from test_step4_restaurants import _get_poi, _row


def _station(poi_id, name, source):
    return {**_row(poi_id, name, "fuel", None, "Rue du Stade, 29217 Plougonvelin"), "source_name": source}


def test_the_query_reads_the_source_of_each_place(monkeypatch):
    _, cursor = _get_poi(monkeypatch, [])
    assert "LEFT JOIN sources src" in cursor.sql and "src.name AS source_name" in cursor.sql


def test_the_same_station_is_shown_once_from_the_state(monkeypatch):
    """L'Intermarché est en base deux fois : par l'ETL OSM et par l'ETL carburants. Seul le second est montré."""
    rows = [_station(1, "Intermarché", "osm"), _station(2, "Intermarché", "prix-carburants")]
    result, _ = _get_poi(monkeypatch, rows)
    assert [poi["id"] for poi in result["gasoil"]] == [2]


def test_a_station_without_state_data_is_never_shown(monkeypatch):
    """Le Total de Portsall, connu d'OSM seul ; une station GPL venue de Park4Night : aucune n'est montrée."""
    rows = [_station(1, "Total", "osm"), _station(2, "Station GPL", "p4n")]
    result, _ = _get_poi(monkeypatch, rows)
    assert result["gasoil"] == []


def test_the_other_services_of_osm_are_kept(monkeypatch):
    rows = [{**_row(1, "Point d'eau", "drinking_water", None, "Port, 29217 Plougonvelin"), "source_name": "osm"}]
    result, _ = _get_poi(monkeypatch, rows)
    assert [poi["name"] for poi in result["eau"]] == ["Point d'eau"]


def test_the_query_reads_the_brand_and_town_of_the_station(monkeypatch):
    _, cursor = _get_poi(monkeypatch, [])
    assert "LEFT JOIN stations_carburant sc" in cursor.sql and "sc.marque AS station_marque" in cursor.sql


def test_a_station_card_links_to_the_station_on_google_maps(monkeypatch):
    rows = [{**_station(2, "Intermarché", "prix-carburants"), "station_marque": "Intermarché",
             "station_code_postal": "29217", "station_ville": "PLOUGONVELIN"}]
    result, _ = _get_poi(monkeypatch, rows)
    assert "query=station-service+Intermarch%C3%A9+Rue+du+Stade" in result["gasoil"][0]["maps_url"]


def test_a_motorway_station_carries_the_motorway_label(monkeypatch):
    """L'Avia de l'A31 près de Gevrey-Chambertin (route = A) porte l'étiquette Autoroute ; une station en ville, non."""
    rows = [{**_station(1, "Avia", "prix-carburants"), "station_route": "A"},
            {**_station(2, "Intermarché", "prix-carburants"), "station_route": "R"}]
    result, cursor = _get_poi(monkeypatch, rows)
    assert "sc.route AS station_route" in cursor.sql
    assert {poi["name"]: poi["autoroute"] for poi in result["gasoil"]} == {"Avia": True, "Intermarché": False}
