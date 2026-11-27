"""
La pause des étapes payantes de la file (services/agents_pause.py, issue #332) : la raison que la supervision affiche
pendant l'attente, et sa fin seule à l'heure dite.
"""
from datetime import datetime

import pytest

from services import agents_pause


@pytest.fixture(autouse=True)
def no_pause():
    """Chaque test part sans pause, et n'en laisse aucune derrière lui."""
    agents_pause.clear()
    yield
    agents_pause.clear()


def test_the_pause_says_when_the_queue_resumes_then_ends_alone():
    """Pendant la pause, la raison dit l'heure de reprise ; l'heure passée, la pause s'efface seule."""
    agents_pause.pause(datetime(2026, 11, 27, 13, 42), "quota des agents atteint")
    assert agents_pause.paused_reason(datetime(2026, 11, 27, 9, 0)) == (
        "quota des agents atteint : la file reprend seule vers 13 h 42")
    assert agents_pause.paused_reason(datetime(2026, 11, 27, 13, 43)) is None


def test_a_longer_pause_is_kept():
    """Une pause courte (trop d'appels) ne raccourcit pas une pause plus longue déjà notée (le quota)."""
    agents_pause.pause(datetime(2026, 11, 27, 13, 42), "quota des agents atteint")
    agents_pause.pause(datetime(2026, 11, 27, 9, 5), "trop d'appels aux agents en même temps")
    assert agents_pause.paused_reason(datetime(2026, 11, 27, 9, 0)).endswith("vers 13 h 42")


def test_without_pause_nothing_waits():
    """Sans limite notée, les étapes payantes n'attendent rien du fournisseur."""
    assert agents_pause.paused_reason(datetime(2026, 11, 27, 9, 0)) is None
