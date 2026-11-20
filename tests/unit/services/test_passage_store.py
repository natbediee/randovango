"""
Les requêtes de la trace des passages (services/passage_store.py, issue #204), sur une base factice qui note ce qu'on
lui demande et rend les lignes qu'on lui donne.
"""
from contextlib import contextmanager

import pytest

from services import passage_store


class _Base:
    """Une base factice : chaque requête est notée avec ses valeurs ; une lecture rend `rows`."""
    def __init__(self, rows=()):
        self.queries, self.rows, self.commits = [], list(rows), 0

    def execute(self, sql, params=None):
        self.queries.append((" ".join(sql.split()), params))

    def fetchall(self):
        return self.rows

    def commit(self):
        self.commits += 1


@pytest.fixture
def base(monkeypatch):
    """La base factice, branchée à la place de MySQLUtils.open_cursor."""
    fake = _Base()

    @contextmanager
    def open_cursor(dictionary=False, buffered=False):
        yield fake, fake

    monkeypatch.setattr(passage_store.MySQLUtils, "open_cursor", open_cursor)
    return fake


def test_a_new_passage_is_queued_with_its_parts_numbered_in_order(base):
    """Un passage demandé est écrit « en file », et ses catégories « à faire », numérotées dans l'ordre où elles passeront."""
    passage_store.insert_passage("p1", "services", 12, "supervision", ["restaurants", "laveries"])
    (passage_sql, passage_values), *parts = base.queries
    assert passage_sql.startswith("INSERT INTO passages") and passage_values[:5] == ("p1", "services", 12, "supervision", "en_file")
    assert [values for _, values in parts] == [("p1", "restaurants", 1, "a_faire"), ("p1", "laveries", 2, "a_faire")]
    assert base.commits == 2


def test_a_running_passage_notes_its_start_and_a_failed_one_its_reason(base):
    """En cours : l'heure de début est notée ; en échec : l'heure de fin et la raison."""
    passage_store.set_passage_status("p1", "en_cours")
    passage_store.set_passage_status("p1", "echec", "délai dépassé")
    (running_sql, _), (failed_sql, failed_values) = base.queries
    assert "started_at" in running_sql and "finished_at" not in running_sql
    assert "finished_at" in failed_sql and failed_values[0] == "echec" and failed_values[2] == "délai dépassé"


def test_the_summary_of_a_part_is_kept_as_json_and_read_back(base):
    """Le bilan de l'enregistrement d'une catégorie est écrit en JSON, et relu en dictionnaire."""
    passage_store.set_part("p1", "restaurants", "fini", summary={"fiches": 4})
    assert '{"fiches": 4}' in base.queries[0][1]
    base.rows = [{"part": "restaurants", "summary": '{"fiches": 4}'}, {"part": "laveries", "summary": None}]
    assert [row["summary"] for row in passage_store.load_parts("p1")] == [{"fiches": 4}, None]


def test_open_parts_count_a_failure_not_yet_resumed(base):
    """Les catégories déjà demandées comptent aussi celles d'un échec pas encore repris, pour ne pas payer une ville deux fois."""
    base.rows = [{"part": "restaurants"}]
    assert passage_store.open_parts("services", [12, 13]) == {"restaurants"}
    sql, values = base.queries[0]
    assert "p.status = 'echec' AND NOT EXISTS" in sql and "r.resumed_from = p.passage_id" in sql
    assert values == ("services", 12, 13)
