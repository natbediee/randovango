"""
La chaîne des spots d'une ville (services/spot_chain.py, issue #276) : la source relue, puis les trois agents limités
aux spots de la ville encore à faire. Ni base, ni navigateur, ni agent : chaque étape est remplacée.
"""
from contextlib import contextmanager

import pandas as pd
import pytest

from agents.find_services import PassageRunning
from etl.extract.scraper_p4n import BrowserNotStarted
from services import spot_chain
from services.etl_chains import StepFailed
from services.spot_chain import SpotsMissed

GUIDEL = {"id": 12, "name": "Guidel"}


def test_the_source_reads_the_city_and_gives_the_number_of_spots(monkeypatch):
    """La source des spots est relue autour de Guidel, chargée sous son nom, et le bilan dit combien de spots ont été lus."""
    loaded = []
    monkeypatch.setattr(spot_chain, "run_p4n_scraper", lambda name, is_headless, save_csv: pd.DataFrame([{"brut": 1}]))
    monkeypatch.setattr(spot_chain, "transform_p4n", lambda raw: ["spot 1", "spot 2"])
    monkeypatch.setattr(spot_chain, "load_p4n_to_mysql", lambda spots, name: loaded.append((spots, name)))
    assert spot_chain.run_source("p1", "source", GUIDEL, False, lambda: None) == {"spots_lus": 2}
    assert loaded == [(["spot 1", "spot 2"], "Guidel")]


def test_an_unreadable_source_fails_with_its_reason(monkeypatch):
    """Une source des spots qui ne répond pas devient un échec avec sa raison, et rien n'est chargé."""
    monkeypatch.setattr(spot_chain, "run_p4n_scraper", lambda name, is_headless, save_csv: None)
    with pytest.raises(StepFailed, match="source des spots illisible"):
        spot_chain.run_source("p1", "source", GUIDEL, False, lambda: None)


def test_a_browser_that_does_not_start_fails_with_its_own_reason(monkeypatch):
    """Un navigateur qui ne démarre pas se dit comme tel, et non « ville sans position ou page qui ne répond pas » (26 novembre 2026)."""
    def refuse(name, is_headless, save_csv):
        raise BrowserNotStarted("le navigateur ne démarre pas (Chrome failed to start)")
    monkeypatch.setattr(spot_chain, "run_p4n_scraper", refuse)
    with pytest.raises(StepFailed, match="le navigateur ne démarre pas") as failure:
        spot_chain.run_source("p1", "source", GUIDEL, False, lambda: None)
    assert "ville sans position" not in str(failure.value)


def test_the_source_lock_closes_leftover_browsers_once_taken(monkeypatch):
    """Le verrou de la source des spots pris, les Chrome restés ouverts sont fermés avant que le passage n'ouvre le sien."""
    events = []

    @contextmanager
    def named_lock(name, busy):
        events.append(f"verrou {name}")
        yield
    monkeypatch.setattr(spot_chain.etl_chains, "named_lock", named_lock)
    monkeypatch.setattr(spot_chain, "close_leftover_browsers", lambda: events.append("Chrome fermés"))
    with spot_chain.lock(12, "source"):
        events.append("passage")
    assert events == ["verrou randovango_passage_spots_source", "Chrome fermés", "passage"]


def test_the_agents_have_their_own_lock_and_close_no_browser(monkeypatch):
    """Les agents des spots prennent leur propre verrou, distinct de la source, et ne ferment aucun Chrome : la source lit pendant qu'ils travaillent (#332)."""
    events = []

    @contextmanager
    def named_lock(name, busy):
        events.append(f"verrou {name}")
        yield
    monkeypatch.setattr(spot_chain.etl_chains, "named_lock", named_lock)
    monkeypatch.setattr(spot_chain, "close_leftover_browsers", lambda: events.append("Chrome fermés"))
    with spot_chain.lock(12, "harmonisation"):
        events.append("passage")
    assert events == ["verrou randovango_passage_spots", "passage"]


def test_a_busy_lock_closes_no_browser(monkeypatch):
    """Un passage de spots déjà en cours garde son navigateur : sans le verrou, aucun Chrome n'est fermé."""
    closed = []

    @contextmanager
    def busy_lock(name, busy):
        raise PassageRunning(busy)
        yield
    monkeypatch.setattr(spot_chain.etl_chains, "named_lock", busy_lock)
    monkeypatch.setattr(spot_chain, "close_leftover_browsers", lambda: closed.append(True))
    with pytest.raises(PassageRunning):
        with spot_chain.lock(12, "source"):
            pass
    assert closed == []


def test_a_source_without_new_spots_finishes_with_zero_spots_read(monkeypatch):
    """Une source relue dont tous les spots sont déjà en base finit avec 0 spot lu, sans échec ni chargement (Ploumoguer, 22 novembre 2026)."""
    loaded = []
    monkeypatch.setattr(spot_chain, "run_p4n_scraper", lambda name, is_headless, save_csv: pd.DataFrame())
    monkeypatch.setattr(spot_chain, "load_p4n_to_mysql", lambda spots, name: loaded.append(name))
    assert spot_chain.run_source("p1", "source", GUIDEL, False, lambda: None) == {"spots_lus": 0}
    assert loaded == []


@pytest.mark.parametrize("part,module,function,key", [
    ("harmonisation", "harmonize_spots", "run_sample", "harmonises"),
    ("ouvertures", "read_openings", "run", "ouvertures_lues"),
    ("verification", "verify_spots", "run", "verifies"),
])
def test_each_agent_works_on_the_city_with_the_budget(monkeypatch, part, module, function, key):
    """Chaque agent reçoit la ville et la vérification du budget, et son bilan devient celui de la partie."""
    asked = {}

    def agent(**kwargs):
        asked.update(kwargs)
        return {"faits": 4, "rates": 0, "erreur": None}

    monkeypatch.setattr(getattr(spot_chain, module), function, agent)
    budget = lambda: None  # noqa: E731
    assert spot_chain.run_part("p1", part, GUIDEL, False, budget) == {key: 4}
    assert asked["city_id"] == 12 and asked["check_budget"] is budget
    # La règle « pas encore fait » : l'harmonisation et la vérification ne prennent que les spots jamais traités.
    assert asked.get("only_new", True) is True


def test_spots_missed_make_the_part_fail_with_the_last_error(monkeypatch):
    """Deux spots ratés sur six (quota) : la partie échoue avec le nombre et l'erreur, au lieu de se dire finie."""
    quota = RuntimeError("You've hit your session limit · resets 1:40pm (UTC)")
    monkeypatch.setattr(spot_chain.harmonize_spots, "run_sample",
                        lambda **kwargs: {"faits": 4, "rates": 2, "erreur": quota})
    with pytest.raises(SpotsMissed) as missed:
        spot_chain.run_part("p1", "harmonisation", GUIDEL, False, lambda: None)
    assert missed.value.missed == 2 and missed.value.done == 4 and missed.value.cause is quota


def test_the_step_of_an_agent_part_is_read_from_its_calls():
    """L'étape d'une partie se lit dans les appels de son agent ; la source n'en a aucun."""
    assert spot_chain.steps_of("harmonisation") == {"harmonize_spots": "harmonisation"}
    assert spot_chain.steps_of("source") == {}
