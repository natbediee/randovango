"""Le retrait des stations-service d'OSM chargées comme services : les voyages passent sur la station de l'État."""
from unittest.mock import MagicMock

from etl import remove_osm_fuel_services as cleanup


def _fake_database(monkeypatch, ids, links):
    """Une base où la recherche des stations OSM rend `ids` et celle des jours de voyage `links` ; rend le faux curseur."""
    cursor = MagicMock()
    cursor.fetchall.side_effect = [[(poi_id,) for poi_id in ids], links]
    cnx = MagicMock()
    cnx.cursor.return_value = cursor
    monkeypatch.setattr(cleanup.MySQLUtils, "connect", lambda: cnx)
    monkeypatch.setattr(cleanup.MySQLUtils, "disconnect", lambda c: None)
    return cnx, cursor


def _queries(cursor) -> list:
    return [" ".join(call.args[0].split()) for call in cursor.execute.call_args_list]


def test_a_trip_day_moves_to_the_state_station_and_loses_a_station_known_only_to_osm(monkeypatch):
    """L'Intermarché de Plougonvelin d'un voyage passe sur la station de l'État ; un Total sans station de l'État part."""
    cnx, cursor = _fake_database(monkeypatch, [78, 8864], [(247, 78, 48526), (620, 8864, None)])
    assert cleanup.remove_osm_fuel_services() == 2
    inserted = [call.args[1] for call in cursor.execute.call_args_list if "INSERT IGNORE" in call.args[0]]
    assert inserted == [(247, 48526)]
    assert _queries(cursor)[-1] == "DELETE FROM poi WHERE id IN (%s, %s)"
    cnx.commit.assert_called_once()


def test_the_rule_decisions_go_with_the_stations(monkeypatch):
    """Les décisions de la règle des doublons sur ces stations sont supprimées avec elles, avant les lieux."""
    _, cursor = _fake_database(monkeypatch, [78], [])
    cleanup.remove_osm_fuel_services()
    queries = _queries(cursor)
    assert queries.index("DELETE FROM decisions WHERE objet_type = 'poi' AND objet_id IN (%s)") \
        < queries.index("DELETE FROM poi WHERE id IN (%s)")


def test_a_trial_writes_nothing(monkeypatch):
    """L'essai (--essai) dit ce qui serait fait, sans rien supprimer ni déplacer."""
    cnx, cursor = _fake_database(monkeypatch, [78], [(247, 78, 48526)])
    assert cleanup.remove_osm_fuel_services(dry_run=True) == 1
    assert not any(query.startswith(("DELETE", "INSERT")) for query in _queries(cursor))
    cnx.commit.assert_not_called()


def test_nothing_to_do_once_the_stations_are_gone(monkeypatch):
    """Relancé après coup, le script ne trouve plus de station OSM dans les services et n'écrit rien."""
    cnx, cursor = _fake_database(monkeypatch, [], [])
    assert cleanup.remove_osm_fuel_services() == 0
    cnx.commit.assert_not_called()
