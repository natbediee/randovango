"""
Le réglage des agents et le budget qui limite leurs passages (services/budget_service.py, issue #211).

Aucune base : le réglage en vigueur et les dépenses de llm_calls sont remplacés par des valeurs posées par chaque test.
"""
from datetime import datetime

import pytest

from services import budget_service

NOW = datetime(2026, 11, 19, 15, 30)


@pytest.fixture
def base(monkeypatch):
    """Le réglage en base (None : personne n'a rien réglé), les lignes écrites, et les dépenses du jour et du mois."""
    state = {"latest": None, "inserted": [], "today": 0.0, "month": 0.0}

    def spent_since(start):
        # Le début du jour (le 19) ou le début du mois (le 1er) : chaque test compte à la date NOW.
        return state["month"] if start.day == 1 else state["today"]

    def insert(settings, changed_by, reason=None):
        state["inserted"].append((settings, changed_by))
        state["latest"] = {**settings, "changed_at": NOW, "changed_by": changed_by, "reason": reason}

    store = budget_service.agent_settings_store
    monkeypatch.setattr(store, "load_latest", lambda: state["latest"])
    monkeypatch.setattr(store, "insert", insert)
    monkeypatch.setattr(store, "spent_since", spent_since)
    return state


def test_without_any_setting_the_test_phase_defaults_apply(base):
    """Tant que l'admin n'a rien réglé, la mise à jour automatique est activée, avec 100 $ par mois, 10 $ par jour et 25 $ pour Vany."""
    state = budget_service.budget_state(NOW)
    assert state["services_apres_etl"] is True
    assert (state["enveloppe_du_mois_usd"], state["plafond_du_jour_usd"], state["reserve_vany_usd"]) == (100, 10, 25)
    assert state["budget_atteint"] is None and state["modifie_par"] is None


def test_a_change_keeps_what_was_not_sent_and_names_the_admin(base):
    """Couper la mise à jour automatique garde le budget tel quel, et la nouvelle ligne porte le nom de l'admin."""
    state = budget_service.save_settings({"services_after_etl": False}, "camille")
    assert base["inserted"] == [({"services_after_etl": False, "monthly_budget_usd": 100.0, "daily_budget_usd": 10.0,
                                  "vany_reserve_usd": 25.0}, "camille")]
    assert state["services_apres_etl"] is False and state["modifie_par"] == "camille"


@pytest.mark.parametrize("changes,message", [
    ({"daily_budget_usd": 150.0}, "plafond du jour"),
    ({"vany_reserve_usd": 120.0}, "part gardée pour Vany"),
])
def test_amounts_that_do_not_fit_together_are_refused(base, changes, message):
    """Un plafond du jour ou une part de Vany plus grands que l'enveloppe du mois sont refusés, et rien n'est écrit."""
    with pytest.raises(ValueError, match=message):
        budget_service.save_settings(changes, "camille")
    assert base["inserted"] == []


def test_the_daily_cap_blocks_until_tomorrow(base):
    """Quand le plafond du jour est atteint, la raison le dit et annonce la reprise pour demain."""
    base["today"], base["month"] = 10.4, 40.0
    state = budget_service.budget_state(NOW)
    assert state["budget_atteint"].startswith("plafond du jour atteint : 10.40 $ dépensés sur 10.00 $")
    assert state["reste_du_jour_usd"] == 0 and state["reste_du_mois_usd"] == 35.0


def test_the_month_envelope_keeps_vany_share(base):
    """Les chaînes d'agents s'arrêtent quand il ne reste que la part de Vany : 75 $ dépensés sur 100 $, avec 25 $ gardés pour elle."""
    base["today"], base["month"] = 2.0, 75.0
    reason = budget_service.budget_state(NOW)["budget_atteint"]
    assert reason.startswith("enveloppe du mois atteinte : 75.00 $ dépensés, 75.00 $ permis aux agents (25.00 $ gardés pour Vany)")
    assert "reprennent le 01/12/2026" in reason


def test_a_raised_cap_lets_passages_go_again(base):
    """Relever le plafond du jour débloque tout de suite, sans redémarrer : le réglage est relu à chaque décision."""
    base["today"], base["month"] = 10.4, 40.0
    assert budget_service.budget_state(NOW)["budget_atteint"] is not None
    budget_service.save_settings({"daily_budget_usd": 20.0}, "camille")
    assert budget_service.budget_state(NOW)["budget_atteint"] is None


def test_the_next_month_of_december_is_january():
    """L'enveloppe de décembre repart le 1er janvier de l'année suivante."""
    assert budget_service.next_month(datetime(2026, 12, 31)) == datetime(2027, 1, 1)


def test_the_reason_of_a_change_is_kept_with_it(base):
    """La raison libre que l'admin donne à un changement est gardée avec lui, et rendue avec le réglage."""
    state = budget_service.save_settings({"daily_budget_usd": 0.0}, "camille", "test du budget atteint")
    assert state["raison_du_changement"] == "test du budget atteint" and state["budget_atteint"] is not None


def test_what_is_left_adds_up_with_what_is_spent(base):
    """Dépensé et restant s'additionnent au centime près : 2,725 $ dépensés sur 10 $ affichent 2,73 $ et 7,27 $ (essai du 19 novembre)."""
    base["today"], base["month"] = 2.725, 40.0
    state = budget_service.budget_state(NOW)
    assert (state["depense_du_jour_usd"], state["reste_du_jour_usd"]) == (2.73, 7.27)
