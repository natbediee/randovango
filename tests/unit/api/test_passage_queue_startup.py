"""
Tests du lancement de la file des passages au démarrage de l'API (backend/main.py) : le backend principal la fait
tourner sans réglage, un backend de branche (PASSAGE_QUEUE_ENABLED=0) ne prend aucun passage de la base commune.
"""
import main
from services import passage_queue


def started_workers(monkeypatch) -> list:
    """Lance le démarrage de la file avec un faux start_worker, et renvoie la liste de ses appels (vide = pas lancée)."""
    calls = []
    monkeypatch.setattr(passage_queue, "start_worker", lambda: calls.append("start"))
    main.start_passage_queue()
    return calls


def test_main_backend_starts_queue_without_setting(monkeypatch):
    """Le backend principal, sans PASSAGE_QUEUE_ENABLED, lance bien les threads de la file des passages."""
    monkeypatch.setenv("ENV", "dev")
    monkeypatch.delenv("PASSAGE_QUEUE_ENABLED", raising=False)
    assert started_workers(monkeypatch) == ["start"]


def test_branch_backend_does_not_start_queue(monkeypatch):
    """Un backend de branche (PASSAGE_QUEUE_ENABLED=0) ne lance aucun thread : cas du 27 novembre, 12 OSM refaits avec un ancien code."""
    monkeypatch.setenv("ENV", "branche")
    monkeypatch.setenv("PASSAGE_QUEUE_ENABLED", "0")
    assert started_workers(monkeypatch) == []


def test_branch_backend_starts_queue_when_asked(monkeypatch):
    """Un backend de branche lancé avec PASSAGE_QUEUE_ENABLED=1 fait tourner la file, puisqu'on le lui demande."""
    monkeypatch.setenv("ENV", "branche")
    monkeypatch.setenv("PASSAGE_QUEUE_ENABLED", "1")
    assert started_workers(monkeypatch) == ["start"]


def test_tests_never_start_queue(monkeypatch):
    """Pendant les tests (ENV=test), la file n'est jamais lancée, même si le réglage la demande."""
    monkeypatch.setenv("ENV", "test")
    monkeypatch.setenv("PASSAGE_QUEUE_ENABLED", "1")
    assert started_workers(monkeypatch) == []
