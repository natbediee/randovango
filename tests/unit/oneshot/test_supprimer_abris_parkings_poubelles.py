import json
from unittest.mock import MagicMock

from oneshot import supprimer_abris_parkings_poubelles as script


def test_human_decisions_sheets_and_other_services_are_kept_out():
    cursor = MagicMock()
    cursor.fetchall.return_value = [{"id": 3}, {"id": 5}, {"id": 9}]
    assert script.target_ids(cursor, limit=2) == [3, 5]
    sql, params = cursor.execute.call_args[0]
    assert "NOT IN" in sql and "FROM restaurants" in sql and "FROM commerces" in sql and "decided_by <> %s" in sql
    assert params == (*script.CATEGORIES, *script.CATEGORIES, script.RULE_AUTHOR)


def test_links_are_deleted_before_the_places():
    cursor = MagicMock()
    cursor.rowcount = 1
    counts = script.delete(cursor, [3, 5])
    tables = [call[0][0].split()[2] for call in cursor.execute.call_args_list]
    assert tables == ["trip_day_pois", "poi_signals", "poi_checks", "histo_poi", "poi_service", "decisions", "poi"]
    assert all(call[0][1] == (3, 5) for call in cursor.execute.call_args_list)
    assert counts["poi"] == 1


def test_counting_deletes_nothing(monkeypatch):
    cursor = MagicMock()
    cursor.fetchall.side_effect = [[{"id": 3}]] + [[] for _ in range(7)]
    connection = MagicMock()
    connection.cursor.return_value = cursor
    monkeypatch.setattr(script.MySQLUtils, "connect", lambda: connection)
    monkeypatch.setattr(script.MySQLUtils, "disconnect", lambda connection: None)
    assert script.main([]) == 0
    assert not any(call[0][0].startswith("DELETE") for call in cursor.execute.call_args_list)
    connection.commit.assert_not_called()


def test_the_backup_keeps_every_row(tmp_path, monkeypatch):
    monkeypatch.setattr(script, "BACKUP_DIR", str(tmp_path))
    path = script.save_backup({"poi": [{"id": 1733, "name": "Accueil"}], "trip_day_pois": [{"trip_day_id": 167, "poi_id": 1733}]})
    saved = json.load(open(path, encoding="utf-8"))
    assert saved["trip_day_pois"][0]["poi_id"] == 1733
