from datetime import date

import pytest

from services import spot_selection_service as selection
from services.spot_selection_service import is_open_on


@pytest.mark.parametrize("status, start, end, night, expected", [
    # Sans période connue, on ne masque rien.
    (None, None, None, date(2027, 1, 15), True),
    ("toute_annee", None, None, date(2027, 1, 15), True),
    ("inconnue", None, None, date(2027, 1, 15), True),
    # Période dans l'année, bornes comprises.
    ("periode", "05-01", "09-30", date(2027, 5, 1), True),
    ("periode", "05-01", "09-30", date(2027, 9, 30), True),
    ("periode", "05-01", "09-30", date(2027, 10, 1), False),
    ("periode", "05-01", "09-30", date(2027, 4, 30), False),
    # Période qui passe par le 1er janvier.
    ("periode", "09-15", "06-15", date(2027, 1, 10), True),
    ("periode", "09-15", "06-15", date(2027, 7, 1), False),
    # KerEmma, "Closed from mid-september" : seule la fin est connue.
    ("periode", None, "09-15", date(2027, 7, 1), True),
    ("periode", None, "09-15", date(2027, 9, 16), False),
    ("periode", None, "09-15", date(2027, 1, 15), False),
    ("periode", None, "09-15", date(2027, 4, 1), True),
    # Seul le début est connu : fermé après le 31 octobre.
    ("periode", "04-03", None, date(2027, 4, 2), False),
    ("periode", "04-03", None, date(2027, 8, 1), True),
    ("periode", "04-03", None, date(2027, 10, 31), True),
    ("periode", "04-03", None, date(2027, 11, 1), False),
    # Une période sans aucune date ne ferme rien.
    ("periode", None, None, date(2027, 1, 15), True),
    # Une saison sans date, "Fermé l'hiver" : la convention du 1er avril au 31 octobre.
    ("saison", None, None, date(2027, 3, 31), False),
    ("saison", None, None, date(2027, 4, 1), True),
    ("saison", None, None, date(2027, 10, 31), True),
    ("saison", None, None, date(2027, 11, 1), False),
])
def test_is_open_on(status, start, end, night, expected) -> None:
    assert is_open_on(status, start, end, night) is expected


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def execute(self, query, params=None):
        self.calls.append((" ".join(query.split()), params))

    def fetchall(self):
        return self.rows


def _spot(spot_id, status=None, start=None, end=None):
    return {"id": spot_id, "ouverture_statut": status, "ouverture_debut": start, "ouverture_fin": end}


def test_proposable_spots_depend_on_the_night(monkeypatch) -> None:
    monkeypatch.setattr(selection, "hidden_spot_ids", lambda *_: {3})
    rows = [_spot(1), _spot(2, "periode", "05-01", "09-30"), _spot(3)]

    summer = selection.proposable_spots(None, FakeCursor(rows), (47, -5, 48, -4), date(2027, 7, 1))
    winter = selection.proposable_spots(None, FakeCursor(rows), (47, -5, 48, -4), date(2027, 12, 1))

    assert [spot["id"] for spot in summer] == [1, 2]  # #3 est retiré en supervision
    assert [spot["id"] for spot in winter] == [1]


def test_proposable_spots_keep_the_permanent_exclusions(monkeypatch) -> None:
    monkeypatch.setattr(selection, "hidden_spot_ids", lambda *_: set())
    cursor = FakeCursor([])
    selection.proposable_spots(None, cursor, (47, -5, 48, -4), date(2027, 7, 1))
    query, _ = cursor.calls[0]
    assert "duplicate_of_spot_id IS NULL" in query
    assert "p4n_removed = 0" in query
    assert "nuit_interdite" in query
    assert "s.type NOT IN" in query
