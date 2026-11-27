"""
Les dépenses des agents jour par jour, lues dans llm_calls (services/agent_settings_store.py), sur une base factice
qui rend les lignes qu'on lui donne. Les heures de la base sont en UTC ; le jour compté est celui de Paris (#299).
"""
from contextlib import contextmanager
from datetime import date, datetime

from services import agent_settings_store


class _Base:
    """Une base factice : elle note la requête et rend `rows`, des totaux heure UTC par heure UTC."""
    def __init__(self, rows):
        self.rows, self.params = rows, None

    def execute(self, sql, params=None):
        self.params = params

    def fetchall(self):
        return self.rows


def _plug(monkeypatch, rows) -> _Base:
    """Branche la base factice à la place de MySQLUtils.open_cursor."""
    fake = _Base(rows)

    @contextmanager
    def open_cursor(dictionary=False, buffered=False):
        yield None, fake
    monkeypatch.setattr(agent_settings_store.MySQLUtils, "open_cursor", open_cursor)
    return fake


def test_the_spending_of_23_h_utc_counts_for_the_next_day_in_paris(monkeypatch):
    """En novembre, ce qu'ont coûté les appels de 22 h UTC reste au 27, ceux de 23 h UTC comptent pour le 28 : il est minuit à Paris."""
    _plug(monkeypatch, [(date(2026, 11, 27), 22, 1.5), (date(2026, 11, 27), 23, 2.0), (date(2026, 11, 28), 0, 0.5)])
    spent = agent_settings_store.spent_by_day(datetime(2026, 11, 26, 23, 0))
    assert spent == {date(2026, 11, 27): 1.5, date(2026, 11, 28): 2.5}


def test_in_summer_the_paris_day_starts_at_22_h_utc(monkeypatch):
    """En juillet, à l'heure d'été, les appels de 22 h UTC le 14 sont déjà ceux du 15 à Paris."""
    _plug(monkeypatch, [(date(2026, 7, 14), 21, 1.0), (date(2026, 7, 14), 22, 3.0)])
    spent = agent_settings_store.spent_by_day(datetime(2026, 7, 13, 22, 0))
    assert spent == {date(2026, 7, 14): 1.0, date(2026, 7, 15): 3.0}


def test_the_spending_is_read_from_the_start_given(monkeypatch):
    """La requête part du début donné, minuit à Paris en heure UTC, sans le décaler."""
    fake = _plug(monkeypatch, [])
    assert agent_settings_store.spent_by_day(datetime(2026, 11, 26, 23, 0)) == {}
    assert fake.params == (datetime(2026, 11, 26, 23, 0),)
