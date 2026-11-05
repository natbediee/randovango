from datetime import date

from agents import mcp_randovango


class FakeCursor:
    """Le spot 85 existe ; la seconde requête renvoie un témoignage."""

    def __init__(self, spot_found=True):
        self.calls = []
        self.spot_found = spot_found

    def execute(self, query, params=None):
        self.calls.append((" ".join(query.split()), params))

    def fetchone(self):
        return (48.67, -4.37, "Kerlouan") if self.spot_found else None

    def fetchall(self):
        return [(date(2026, 3, 28), "(29890) Kerlouan - 12 Kerlouarn", "Pas de panneau d'interdiction la nuit.")]


def test_testimonies_come_from_other_spots_of_the_commune_and_talk_about_night_rules() -> None:
    cursor = FakeCursor()
    rows = mcp_randovango.commune_testimonies(cursor, 85)
    query, params = cursor.calls[1]
    assert "s.id <> %s" in query                       # pas le spot lui-même
    assert "s.city_label = %s" in query                # même commune...
    assert "s.latitude BETWEEN %s AND %s" in query     # ... ou à moins de ~3 km
    # Deux filtres : une règle ET le stationnement de nuit (écarte "panneau du robinet").
    assert params[-3:] == (mcp_randovango.RULE_WORDS, mcp_randovango.NIGHT_WORDS, mcp_randovango.MAX_TESTIMONIES)
    assert rows[0][1] == "(29890) Kerlouan - 12 Kerlouarn"


def test_unknown_spot_returns_nothing() -> None:
    assert mcp_randovango.commune_testimonies(FakeCursor(spot_found=False), 999) == []
