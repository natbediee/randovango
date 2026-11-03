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
