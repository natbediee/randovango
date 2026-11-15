"""
La relecture des toilettes et douches d'OSM déjà en base (etl/etl_toilettes.py, issue #248) : chaque toilette lue
reçoit ses étiquettes access et fee, une toilette absente d'OSM part en relecture, une non lue n'est pas touchée.
"""
from unittest.mock import MagicMock

from etl import etl_toilettes


def _facility(poi_id, osm_id, acces_osm=None, latitude=48.3400, longitude=-4.7200):
    """Une toilette d'OSM telle que load_facilities la lit dans la base."""
    return {"id": poi_id, "name": "Toilettes publiques", "original_id": osm_id, "latitude": latitude,
            "longitude": longitude, "acces_osm": acces_osm, "type": "toilets"}


def _element(osm_id, tags, latitude=48.3400, longitude=-4.7200):
    """Un objet OSM tel qu'extract_osm_by_ids le renvoie."""
    return {"type": "node", "id": int(osm_id), "lat": latitude, "lon": longitude, "tags": tags}


def test_customers_toilet_gets_its_tag() -> None:
    """Une toilette de camping jamais relue reçoit access=customers, que l'étape 4 cachera."""
    elements = {"101": [_element("101", {"amenity": "toilets", "access": "customers"})]}
    read, absent, not_read = etl_toilettes.sort_facilities([_facility(1, "101")], elements, set())
    assert [(facility["id"], facility["access"]) for facility in read] == [(1, "customers")]
    assert absent == [] and not_read == []


def test_public_toilet_gets_yes_and_fee() -> None:
    """Une toilette publique payante reçoit access=yes et payant=1 : montrée « Vérifié » avec le badge Payant."""
    elements = {"102": [_element("102", {"amenity": "toilets", "access": "yes", "fee": "yes"})]}
    read, _, _ = etl_toilettes.sort_facilities([_facility(2, "102")], elements, set())
    assert (read[0]["access"], read[0]["payant"]) == ("yes", 1)


def test_element_far_away_is_not_the_same_toilet() -> None:
    """Un way au même numéro mais à des kilomètres n'est pas la toilette : elle est rangée parmi les absentes."""
    elements = {"103": [_element("103", {"amenity": "toilets", "access": "yes"}, latitude=47.99, longitude=-4.10)]}
    read, absent, _ = etl_toilettes.sort_facilities([_facility(3, "103")], elements, set())
    assert read == [] and [facility["id"] for facility in absent] == [3]


def test_deleted_or_retagged_toilet_is_absent() -> None:
    """Une toilette supprimée d'OSM, ou devenue autre chose (un café), est absente : elle part en relecture."""
    elements = {"105": [_element("105", {"amenity": "cafe"})]}
    facilities = [_facility(4, "104"), _facility(5, "105")]
    read, absent, _ = etl_toilettes.sort_facilities(facilities, elements, set())
    assert read == [] and [facility["id"] for facility in absent] == [4, 5]


def test_unread_toilet_is_left_alone() -> None:
    """Une toilette d'un paquet qu'Overpass n'a pas rendu n'est ni lue ni absente : son absence ne prouve rien."""
    read, absent, not_read = etl_toilettes.sort_facilities([_facility(6, "106")], {}, {"106"})
    assert read == [] and absent == [] and [facility["id"] for facility in not_read] == [6]


def test_report_counts_tags_before_and_after() -> None:
    """Le bilan compte les toilettes par étiquette access, avant -> après, « (aucune) » quand elle manque."""
    read = [{"acces_osm": None, "access": "yes"}, {"acces_osm": None, "access": "yes"},
            {"acces_osm": "yes", "access": None}]
    assert etl_toilettes.count_changes(read) == {("(aucune)", "yes"): 2, ("yes", "(aucune)"): 1}


def test_write_results_updates_tags_and_flags_absent(monkeypatch) -> None:
    """Le passage réel écrit l'étiquette d'une toilette lue et un signal absent_osm pour une absente, puis valide."""
    connection = MagicMock()
    cursor = connection.cursor.return_value
    monkeypatch.setattr(etl_toilettes.MySQLUtils, "connect", lambda: connection)
    monkeypatch.setattr(etl_toilettes.MySQLUtils, "disconnect", lambda cnx: None)
    read = [{**_facility(1, "101"), "access": "customers", "payant": None}]
    etl_toilettes.write_results(read, [_facility(4, "104")])
    queries = [call.args[0] for call in cursor.execute.call_args_list]
    assert queries[0].startswith("UPDATE poi SET acces_osm")
    assert cursor.execute.call_args_list[0].args[1] == ("customers", None, 1)
    assert "INSERT INTO poi_signals" in queries[1] and cursor.execute.call_args_list[1].args[1][2] == "absent_osm"
    connection.commit.assert_called_once()


def test_dry_run_writes_nothing(monkeypatch) -> None:
    """En --essai, OSM est lu et le bilan affiché, mais rien n'est écrit dans la base."""
    monkeypatch.setattr(etl_toilettes, "load_facilities", lambda: [_facility(1, "101")])
    elements = {"101": [_element("101", {"amenity": "toilets", "access": "yes"})]}
    monkeypatch.setattr(etl_toilettes, "extract_osm_by_ids", lambda ids: (elements, set()))
    write = MagicMock()
    monkeypatch.setattr(etl_toilettes, "write_results", write)
    read, _, _ = etl_toilettes.run(dry_run=True)
    assert read[0]["access"] == "yes"
    write.assert_not_called()
