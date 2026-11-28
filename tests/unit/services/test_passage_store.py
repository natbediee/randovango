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


def test_finished_parts_are_read_in_every_passage_of_the_commune(base):
    """Les catégories finies se lisent dans tous les passages des villes de la commune, même un échec, d'après l'état de la partie."""
    base.rows = [{"part": "laveries"}]
    assert passage_store.finished_parts("services", [12]) == {"laveries"}
    sql, values = base.queries[0]
    # L'état du passage n'est pas regardé : une catégorie finie avant une coupure reste faite.
    assert "pp.status = 'fini'" in sql and "p.status IN" not in sql
    assert values == ("services", 12)


def test_the_running_passages_are_read_for_one_chain_only(base):
    """Le passage en cours se cherche dans la chaîne lancée : un passage d'une autre chaîne n'est pas nommé à sa place."""
    base.rows = [{"passage_id": "p1"}]
    assert passage_store.running_ids("services") == ["p1"]
    sql, values = base.queries[0]
    assert "chain = %s" in sql and values == ("en_cours", "services")


def test_the_active_passages_are_read_for_one_chain_on_one_city(base):
    """Les passages qui referont déjà la chaîne sur la ville : en file, en attente ou en cours, pas les échecs (#329)."""
    base.rows = [{"passage_id": "p1"}]
    assert passage_store.active_ids("carburants", 12) == ["p1"]
    sql, values = base.queries[0]
    assert "status IN ('en_file', 'en_attente', 'en_cours')" in sql and values == ("carburants", 12)


def test_the_queue_is_read_from_the_oldest_passage_with_its_next_part(base):
    """La file se lit demandes admin d'abord (#356), puis du plus ancien passage au plus récent, chacun avec sa prochaine partie à faire : elle dit son étape (#332)."""
    base.rows = [{"passage_id": "p1", "chain": "spots", "city_id": 12, "next_part": "harmonisation"}]
    assert passage_store.queued_next_parts() == base.rows
    sql, values = base.queries[0]
    assert "ORDER BY p.origin NOT IN (%s, %s), p.requested_at, p.passage_id" in sql
    assert "ORDER BY pp.position LIMIT 1" in sql
    assert values == ("a_faire", "en_file", "supervision", "ajout")


def test_a_pending_part_is_looked_for_in_the_other_open_passages_of_the_cities(base):
    """L'étape d'avant attendue (l'OSM de la ville) se cherche dans les autres passages ouverts ou en échec non repris (#332)."""
    base.rows = [{"1": 1}]
    assert passage_store.pending_part("osm", "osm", [12, 13], "p9") is True
    sql, values = base.queries[0]
    assert "pp.status <> 'fini'" in sql and "p.passage_id <> %s" in sql and "r.resumed_from = p.passage_id" in sql
    assert values == ("osm", "osm", 12, 13, "p9")


def test_the_failures_to_resume_are_etl_failures_of_the_free_chains_not_yet_resumed(base):
    """Les échecs à reprendre seuls sont ceux de l'ETL sur les chaînes données, finis depuis la date donnée, que personne n'a repris."""
    from datetime import datetime
    since = datetime(2026, 11, 24, 12, 0)
    base.rows = [{"passage_id": "p1", "chain": "osm", "city_id": 12, "resumed_from": None, "finished_at": since}]
    assert passage_store.failures_to_resume(("osm", "finess"), since)[0]["passage_id"] == "p1"
    sql, values = base.queries[0]
    assert "p.origin = 'etl'" in sql and "NOT EXISTS" in sql and "ORDER BY p.finished_at" in sql
    assert values == ("echec", "osm", "finess", since)


def test_an_item_is_noted_under_the_running_passage_without_committing(base):
    """Un spot harmonisé est noté sous le passage en cours, avec le curseur de l'écriture : la ligne entre avec elle."""
    from agents.llm_service import mesure_passage
    with mesure_passage("p1"):
        passage_store.note_item(base, "spot", 3893, passage_store.CHANGED, "harmonisation")
    sql, values = base.queries[0]
    assert sql.startswith("INSERT INTO passage_items") and values[:5] == ("p1", "spot", 3893, "modification", "harmonisation")
    assert base.commits == 0


def test_nothing_is_noted_outside_a_passage(base):
    """Une écriture faite hors de tout passage (un essai) n'est pas notée dans le journal."""
    passage_store.note_item(base, "spot", 3893, passage_store.CHANGED, "harmonisation")
    assert base.queries == []


def test_the_items_of_a_passage_come_with_their_names(base):
    """Ce qu'un passage a trouvé se lit avec le nom de chaque service, spot ou pépite, et se filtre sur un objet."""
    passage_store.load_items("p1")
    passage_store.load_items("p1", "spot", 3893)
    (all_sql, all_values), (one_sql, one_values) = base.queries
    assert "COALESCE(p.name, s.name, pe.nom) AS item_name" in all_sql and all_values == ("p1",)
    assert "i.item_type = %s AND i.item_id = %s" in one_sql and one_values == ("p1", "spot", 3893)


def test_the_passages_of_an_item_are_read_from_the_most_recent(base):
    """Pour une information, les passages qui l'ont apportée se lisent du plus récent au plus ancien."""
    base.rows = [{"passage_id": "p2"}, {"passage_id": "p1"}]
    assert passage_store.passages_of_item("spot", 3893) == ["p2", "p1"]
    assert "ORDER BY last_written DESC" in base.queries[0][0] and base.queries[0][1] == ("spot", 3893)
