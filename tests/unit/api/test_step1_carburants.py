"""
Le rafraîchissement des prix des carburants au début d'un voyage (api/routers/step1.start_fuel_prices_refresh) :
une fois par jour, dans un fil à part, sans jamais faire échouer la page. Ni réseau ni base : la date du dernier
rafraîchissement, refresh_prices et le fil sont remplacés.
"""
from datetime import datetime, timedelta

import pytest

from api.routers import step1


class FakeThread:
    """Un fil qui ne part pas tout seul : le test choisit quand il tourne."""
    started = []

    def __init__(self, target, daemon=False):
        self.target, self.daemon = target, daemon

    def start(self):
        FakeThread.started.append(self)


@pytest.fixture(autouse=True)
def fresh_state(monkeypatch):
    FakeThread.started = []
    monkeypatch.setattr(step1.threading, "Thread", FakeThread)
    monkeypatch.setattr(step1, "fuel_refresh_in_progress", False)
    monkeypatch.setattr(step1, "fuel_refresh_failed_at", None)


def test_prices_already_read_today_are_not_refreshed(monkeypatch):
    """Des prix déjà relus aujourd'hui : aucun fil n'est lancé, le fichier de l'État n'est pas retéléchargé."""
    monkeypatch.setattr(step1, "prices_read_at", lambda: datetime.now() - timedelta(minutes=5))
    assert step1.start_fuel_prices_refresh() is False
    assert FakeThread.started == []


def test_prices_read_yesterday_are_refreshed_in_the_background(monkeypatch):
    """Des prix d'hier : refresh_prices part dans un fil daemon, et la page n'attend pas sa fin."""
    monkeypatch.setattr(step1, "prices_read_at", lambda: datetime.now() - timedelta(days=1))
    calls = []
    monkeypatch.setattr(step1, "refresh_prices", lambda: calls.append("prix") or 163)
    assert step1.start_fuel_prices_refresh() is True
    assert len(FakeThread.started) == 1 and FakeThread.started[0].daemon is True
    assert calls == []
    FakeThread.started[0].target()
    assert calls == ["prix"]
    assert step1.fuel_refresh_in_progress is False


def test_prices_never_read_are_refreshed(monkeypatch):
    """Aucun rafraîchissement noté (sources.lu_le vide) : les prix sont relus."""
    monkeypatch.setattr(step1, "prices_read_at", lambda: None)
    assert step1.start_fuel_prices_refresh() is True


def test_two_simultaneous_calls_start_a_single_refresh(monkeypatch):
    """Deux voyageurs ouvrent la page en même temps : un seul rafraîchissement, le second voit le drapeau « en cours »."""
    monkeypatch.setattr(step1, "prices_read_at", lambda: None)
    assert step1.start_fuel_prices_refresh() is True
    assert step1.start_fuel_prices_refresh() is False
    assert len(FakeThread.started) == 1


def test_a_failed_refresh_never_raises_and_waits_before_retrying(monkeypatch):
    """Un échec de refresh_prices (erreur de base) est noté sans remonter ; la page suivante ne relance pas aussitôt."""
    monkeypatch.setattr(step1, "prices_read_at", lambda: None)

    def broken():
        raise RuntimeError("MySQL injoignable")

    monkeypatch.setattr(step1, "refresh_prices", broken)
    step1.start_fuel_prices_refresh()
    FakeThread.started[0].target()
    assert step1.fuel_refresh_in_progress is False
    assert step1.fuel_refresh_failed_at is not None
    assert step1.start_fuel_prices_refresh() is False
    assert len(FakeThread.started) == 1


def test_a_missing_state_file_counts_as_a_failure(monkeypatch):
    """Le site de l'État ne répond pas (refresh_prices renvoie None) : c'est un échec, les anciens prix restent."""
    monkeypatch.setattr(step1, "prices_read_at", lambda: None)
    monkeypatch.setattr(step1, "refresh_prices", lambda: None)
    step1.start_fuel_prices_refresh()
    FakeThread.started[0].target()
    assert step1.fuel_refresh_failed_at is not None


def test_a_refresh_is_retried_after_the_delay(monkeypatch):
    """Une heure après un échec, la page relance le rafraîchissement."""
    monkeypatch.setattr(step1, "prices_read_at", lambda: None)
    monkeypatch.setattr(step1, "fuel_refresh_failed_at",
                        datetime.now() - timedelta(minutes=step1.FUEL_RETRY_MINUTES + 1))
    assert step1.start_fuel_prices_refresh() is True


def test_an_unreadable_date_never_breaks_the_page(monkeypatch):
    """La colonne sources.lu_le absente (db_init pas encore lancé) : rien n'est lancé et aucune erreur ne remonte."""
    def broken():
        raise RuntimeError("Unknown column 'lu_le'")

    monkeypatch.setattr(step1, "prices_read_at", broken)
    assert step1.start_fuel_prices_refresh() is False
    assert FakeThread.started == []
