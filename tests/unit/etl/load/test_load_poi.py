"""Tests du chargement des services d'OSM dans la table poi (etl/load/load_poi.py)."""
from unittest.mock import MagicMock

from etl.load.load_poi import save_public_access


def test_toilet_access_is_written_even_when_already_in_base() -> None:
    """Une toilette déjà en base reçoit son étiquette access par un UPDATE, que l'INSERT IGNORE ne ferait pas."""
    cursor = MagicMock()
    save_public_access(cursor, 42, {"type": "toilets", "access": "customers", "payant": 1.0})
    cursor.execute.assert_called_once_with("UPDATE poi SET acces_osm = %s, payant = %s WHERE id = %s",
                                           ("customers", 1, 42))


def test_removed_tags_go_back_to_null() -> None:
    """Une douche sans étiquette (case vide NaN du tableau pandas) revient à NULL, pas à NaN."""
    cursor = MagicMock()
    save_public_access(cursor, 7, {"type": "shower", "access": None, "payant": float("nan")})
    assert cursor.execute.call_args.args[1] == (None, None, 7)


def test_other_services_are_not_touched() -> None:
    """Un restaurant d'OSM ne reçoit pas d'étiquette access : rien n'est écrit."""
    cursor = MagicMock()
    save_public_access(cursor, 3, {"type": "restaurant"})
    cursor.execute.assert_not_called()
