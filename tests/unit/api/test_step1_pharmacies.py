"""
La relecture de FINESS au début d'un voyage (api/routers/step1.start_pharmacies_refresh, carte #241) : une fois par
jour, dans un fil à part, sans jamais faire échouer la page. Ni réseau ni base : la date de la dernière relecture,
refresh_pharmacies et le fil sont remplacés.
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
    monkeypatch.setattr(step1, "pharmacy_refresh_in_progress", False)
    monkeypatch.setattr(step1, "pharmacy_refresh_failed_at", None)


def test_finess_already_read_today_is_not_read_again(monkeypatch):
    """FINESS déjà relu aujourd'hui : aucun fil n'est lancé, les 52 Mo ne sont pas retéléchargés."""
    monkeypatch.setattr(step1, "pharmacies_read_at", lambda: datetime.now() - timedelta(minutes=5))
    assert step1.start_pharmacies_refresh() is False
    assert FakeThread.started == []


def test_finess_read_yesterday_is_read_again_in_the_background(monkeypatch):
    """FINESS relu hier : refresh_pharmacies part dans un fil daemon, et la page n'attend pas sa fin."""
    monkeypatch.setattr(step1, "pharmacies_read_at", lambda: datetime.now() - timedelta(days=1))
    calls = []
    monkeypatch.setattr(step1, "refresh_pharmacies", lambda: calls.append("finess") or 580)
    assert step1.start_pharmacies_refresh() is True
    assert len(FakeThread.started) == 1 and FakeThread.started[0].daemon is True
    assert calls == []
    FakeThread.started[0].target()
    assert calls == ["finess"]
    assert step1.pharmacy_refresh_in_progress is False


def test_finess_never_read_is_read(monkeypatch):
    """Aucune relecture notée (sources.lu_le vide, comme après le chargement de #194) : FINESS est relu."""
    monkeypatch.setattr(step1, "pharmacies_read_at", lambda: None)
    assert step1.start_pharmacies_refresh() is True


def test_two_simultaneous_calls_start_a_single_reading(monkeypatch):
    """Deux voyageurs ouvrent la page en même temps : une seule relecture, le second voit le drapeau « en cours »."""
    monkeypatch.setattr(step1, "pharmacies_read_at", lambda: None)
    assert step1.start_pharmacies_refresh() is True
    assert step1.start_pharmacies_refresh() is False
    assert len(FakeThread.started) == 1


def test_a_failed_reading_never_raises_and_waits_before_retrying(monkeypatch):
    """Une erreur de refresh_pharmacies (base injoignable) est notée sans remonter ; la page suivante ne relance pas."""
    monkeypatch.setattr(step1, "pharmacies_read_at", lambda: None)

    def broken():
        raise RuntimeError("MySQL injoignable")

    monkeypatch.setattr(step1, "refresh_pharmacies", broken)
    step1.start_pharmacies_refresh()
    FakeThread.started[0].target()
    assert step1.pharmacy_refresh_in_progress is False
    assert step1.pharmacy_refresh_failed_at is not None
    assert step1.start_pharmacies_refresh() is False
    assert len(FakeThread.started) == 1


def test_a_missing_finess_file_counts_as_a_failure(monkeypatch):
    """data.gouv.fr ne répond pas (refresh_pharmacies renvoie None) : c'est un échec, les pharmacies en base restent."""
    monkeypatch.setattr(step1, "pharmacies_read_at", lambda: None)
    monkeypatch.setattr(step1, "refresh_pharmacies", lambda: None)
    step1.start_pharmacies_refresh()
    FakeThread.started[0].target()
    assert step1.pharmacy_refresh_failed_at is not None


def test_a_reading_is_retried_after_the_delay(monkeypatch):
    """Une heure après un échec, la page relance la relecture de FINESS."""
    monkeypatch.setattr(step1, "pharmacies_read_at", lambda: None)
    monkeypatch.setattr(step1, "pharmacy_refresh_failed_at",
                        datetime.now() - timedelta(minutes=step1.PHARMACY_RETRY_MINUTES + 1))
    assert step1.start_pharmacies_refresh() is True


def test_an_unreadable_date_never_breaks_the_page(monkeypatch):
    """La date de relecture illisible (base injoignable) : rien n'est lancé et aucune erreur ne remonte."""
    def broken():
        raise RuntimeError("MySQL injoignable")

    monkeypatch.setattr(step1, "pharmacies_read_at", broken)
    assert step1.start_pharmacies_refresh() is False
    assert FakeThread.started == []
