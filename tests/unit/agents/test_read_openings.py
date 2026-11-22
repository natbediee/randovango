from datetime import date

from agents import read_openings


def test_period_keeps_valid_dates_only() -> None:
    assert read_openings.normalize({"statut": "periode", "debut": "05-01", "fin": "09-30"}) == {
        "statut": "periode", "debut": "05-01", "fin": "09-30"}
    assert read_openings.normalize({"statut": "periode", "debut": None, "fin": "09-15"}) == {
        "statut": "periode", "debut": None, "fin": "09-15"}


def test_a_badly_formed_date_never_closes_a_spot() -> None:
    assert read_openings.normalize({"statut": "periode", "debut": "13-45", "fin": "fin août"}) == {
        "statut": "inconnue", "debut": None, "fin": None}
    assert read_openings.normalize({"statut": "periode", "debut": None, "fin": None})["statut"] == "inconnue"


def test_only_a_period_keeps_dates() -> None:
    assert read_openings.normalize({"statut": "toute_annee", "debut": "05-01", "fin": "09-30"}) == {
        "statut": "toute_annee", "debut": None, "fin": None}
    assert read_openings.normalize({"statut": "autre"})["statut"] == "inconnue"


def test_a_season_has_no_dates_in_the_database() -> None:
    assert read_openings.normalize({"statut": "saison", "debut": "04-01", "fin": "10-31"}) == {
        "statut": "saison", "debut": None, "fin": None}


def test_message_gives_the_date_the_text_and_the_description() -> None:
    message = read_openings.build_user_message("Closed from mid-september", "Ouvert toute l'année")
    assert f"DATE DU JOUR : {date.today():%d/%m/%Y}" in message
    assert 'OUVERTURE : "Closed from mid-september"' in message
    assert 'DESCRIPTION : "Ouvert toute l\'année"' in message


def test_message_cuts_a_long_description() -> None:
    message = read_openings.build_user_message("En saison", "x" * 5000)
    assert "x" * read_openings.MAX_DESCRIPTION_CHARS in message
    assert "x" * (read_openings.MAX_DESCRIPTION_CHARS + 1) not in message


def test_prompt_keeps_seasons_with_a_past_year_and_drops_one_off_closures() -> None:
    assert "même si cette année est passée" in read_openings.SYSTEM_PROMPT
    assert "fermeture d'une seule année" in read_openings.SYSTEM_PROMPT


class FakeCursor:
    def __init__(self, rows=()):
        self.rows = rows
        self.calls = []

    def execute(self, query, params=None):
        self.calls.append((" ".join(query.split()), params))

    def fetchall(self):
        return self.rows


def test_all_year_and_already_read_spots_are_not_selected() -> None:
    cursor = FakeCursor()
    read_openings.fetch_spots_to_read(cursor, limit=5)
    query, params = cursor.calls[0]
    assert "ouverture_lue IS NULL OR ouverture_lue <> opening_period" in query
    assert params[0] == read_openings.ALL_YEAR
    assert params[-1] == 5


def test_a_human_decision_is_never_read_again() -> None:
    for kwargs in ({"limit": 5}, {"spot_ids": [1, 2]}):
        cursor = FakeCursor()
        read_openings.fetch_spots_to_read(cursor, **kwargs)
        query, _ = cursor.calls[0]
        assert "NOT EXISTS (SELECT 1 FROM decisions d WHERE d.objet_type = 'ouverture'" in query
        assert "d.annulee_at IS NULL" in query


def test_write_keeps_the_text_that_was_read_and_never_touches_the_source() -> None:
    cursor = FakeCursor()
    read_openings.write_opening(cursor, 1, "Avril à septembre", {"statut": "periode", "debut": "04-01", "fin": "09-30"})
    query, params = cursor.calls[0]
    assert "opening_period =" not in query
    assert params == ("periode", "04-01", "09-30", "Avril à septembre", 1)


def test_a_city_keeps_only_its_spots_not_read_yet() -> None:
    """Pour une ville, seuls ses spots (histo_scrap) au texte d'ouverture pas encore lu sont pris : rien n'est relu."""
    cursor = FakeCursor()
    read_openings.fetch_spots_to_read(cursor, city_id=12)
    query, params = cursor.calls[0]
    assert "ouverture_lue IS NULL OR ouverture_lue <> opening_period" in query
    assert "AND id IN (SELECT spot_id FROM histo_scrap WHERE city_id = %s)" in query
    assert params[-1] == 12


def test_a_city_run_gives_its_summary_and_stops_on_the_budget(monkeypatch) -> None:
    """Le bilan dit les textes lus et ratés ; quand le budget des agents est atteint, la lecture s'arrête avant le spot suivant."""
    import pytest
    from unittest.mock import MagicMock

    class BudgetReached(RuntimeError):
        pass

    class Service:
        def complete_json(self, system, user, schema):
            if "panne" in user:
                raise read_openings.LLMUnavailable("Error code: 529 overloaded_error")
            return {"statut": "toute_annee"}

    written = []
    spots = [{"id": 1, "opening_period": "Avril à septembre", "description": None},
             {"id": 2, "opening_period": "panne", "description": None},
             {"id": 3, "opening_period": "Juin", "description": None}]
    monkeypatch.setattr(read_openings.MySQLUtils, "connect", lambda: MagicMock())
    monkeypatch.setattr(read_openings.MySQLUtils, "disconnect", lambda connection: None)
    monkeypatch.setattr(read_openings, "fetch_spots_to_read", lambda cursor, limit, spot_ids, city_id: spots[:2])
    monkeypatch.setattr(read_openings, "write_opening", lambda cursor, spot_id, text, payload: written.append(spot_id))
    summary = read_openings.run(service=Service(), city_id=12)
    assert written == [1] and summary["faits"] == 1 and summary["rates"] == 1
    assert "overloaded" in str(summary["erreur"])

    monkeypatch.setattr(read_openings, "fetch_spots_to_read", lambda cursor, limit, spot_ids, city_id: spots)

    def check_budget():
        if written:
            raise BudgetReached("plafond du jour atteint")
    written.clear()
    with pytest.raises(BudgetReached):
        read_openings.run(service=Service(), city_id=12, check_budget=check_budget)
    assert written == [1]


def test_an_opening_read_is_noted_in_the_journal_of_its_passage(monkeypatch) -> None:
    """Les dates d'ouverture lues pour un spot sont notées dans le journal du passage, partie « ouvertures »."""
    from unittest.mock import MagicMock

    class Service:
        def complete_json(self, system, user, schema):
            return {"statut": "periode", "debut": "11-06", "fin": "03-31"}

    noted = []
    monkeypatch.setattr(read_openings.MySQLUtils, "connect", lambda: MagicMock())
    monkeypatch.setattr(read_openings.MySQLUtils, "disconnect", lambda connection: None)
    monkeypatch.setattr(read_openings, "fetch_spots_to_read", lambda cursor, limit, spot_ids, city_id: [
        {"id": 3894, "opening_period": "Overnight is forbidden between 01.04.- 05.11", "description": None}])
    monkeypatch.setattr(read_openings, "write_opening", lambda cursor, spot_id, text, payload: None)
    monkeypatch.setattr(read_openings.passage_store, "note_item",
                        lambda cursor, kind, item_id, action, part: noted.append((kind, item_id, action, part)))
    read_openings.run(service=Service(), city_id=50)
    assert noted == [("spot", 3894, "modification", "ouvertures")]
