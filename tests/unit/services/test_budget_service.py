"""
Le réglage des agents et le budget qui limite leurs passages (services/budget_service.py, issues #211 et #275).

Aucune base ni réseau : le réglage en vigueur, les dépenses de llm_calls et le taux de la BCE sont remplacés par des
valeurs posées par chaque test. Le taux par défaut, 1,20 $ pour un euro, compense exactement la TVA de 20 % : un dollar
dépensé fait alors un euro TTC, et les montants se lisent sans calcul.
"""
from datetime import date, datetime

import pytest

from services import budget_service
from services.exchange_rate_service import RateUnavailable

NOW = datetime(2026, 11, 19, 15, 30)
TODAY, FIRST_OF_MONTH = date(2026, 11, 19), date(2026, 11, 1)


def rate(usd_per_eur, day=TODAY):
    """Un taux de la BCE tel que le rend exchange_rate_service.rate_for."""
    return {"usd_per_eur": usd_per_eur, "rate_date": day, "same_day": True}


@pytest.fixture
def base(monkeypatch):
    """
    Le réglage en base (None : personne n'a rien réglé), les lignes écrites, les dépenses en dollars du jour et du
    mois, et le taux de chaque jour (rates, 1,20 par défaut ; None : aucun taux connu).
    """
    state = {"latest": None, "inserted": [], "today": 0.0, "month": 0.0, "rates": {}}

    def spent_by_day(start):
        # Le début du jour (le 19) ou le début du mois (le 1er) : chaque test compte à la date NOW.
        if start.day != 1:
            return {TODAY: state["today"]}
        return {FIRST_OF_MONTH: state["month"] - state["today"], TODAY: state["today"]}

    def insert(settings, changed_by, reason=None):
        state["inserted"].append((settings, changed_by))
        state["latest"] = {**settings, "changed_at": NOW, "changed_by": changed_by, "reason": reason}

    def rate_for(day):
        if state["rates"] is None:
            raise RateUnavailable("aucun taux de la BCE connu")
        return rate(state["rates"].get(day, 1.20), day)

    store = budget_service.agent_settings_store
    monkeypatch.setattr(store, "load_latest", lambda: state["latest"])
    monkeypatch.setattr(store, "insert", insert)
    monkeypatch.setattr(store, "spent_by_day", spent_by_day)
    monkeypatch.setattr(budget_service.exchange_rate_service, "rate_for", rate_for)
    return state


def test_without_any_setting_the_test_phase_defaults_apply(base):
    """Tant que l'admin n'a rien réglé, la mise à jour automatique est activée, avec 100 € par mois, 10 € par jour et 25 € pour Vany."""
    state = budget_service.budget_state(NOW)
    assert state["services_apres_etl"] is True
    assert (state["enveloppe_du_mois_eur"], state["plafond_du_jour_eur"], state["reserve_vany_eur"]) == (100, 10, 25)
    assert state["budget_atteint"] is None and state["modifie_par"] is None


def test_a_change_keeps_what_was_not_sent_and_names_the_admin(base):
    """Couper la mise à jour automatique garde le budget tel quel, et la nouvelle ligne porte le nom de l'admin."""
    state = budget_service.save_settings({"services_after_etl": False}, "camille")
    [(settings, changed_by)] = base["inserted"]
    assert changed_by == "camille" and settings["services_after_etl"] is False
    assert (settings["monthly_budget_eur"], settings["daily_budget_eur"], settings["vany_reserve_eur"]) == (100, 10, 25)
    assert state["services_apres_etl"] is False and state["modifie_par"] == "camille"


def test_the_amounts_set_in_euros_are_also_written_in_dollars_at_the_rate_of_the_day(base):
    """Un plafond de 6 € réglé un jour où l'euro vaut 1,08 $ est aussi écrit 5,40 $ (TVA retirée), pour les branches qui lisent les dollars."""
    base["rates"] = {date.today(): 1.08}
    budget_service.save_settings({"daily_budget_eur": 6.0}, "camille")
    [(settings, _)] = base["inserted"]
    assert (settings["daily_budget_eur"], settings["daily_budget_usd"]) == (6.0, 5.4)


@pytest.mark.parametrize("changes,message", [
    ({"daily_budget_eur": 150.0}, "plafond du jour"),
    ({"vany_reserve_eur": 120.0}, "part gardée pour Vany"),
])
def test_amounts_that_do_not_fit_together_are_refused(base, changes, message):
    """Un plafond du jour ou une part de Vany plus grands que l'enveloppe du mois sont refusés, et rien n'est écrit."""
    with pytest.raises(ValueError, match=message):
        budget_service.save_settings(changes, "camille")
    assert base["inserted"] == []


def test_the_daily_cap_blocks_until_tomorrow(base):
    """Quand le plafond du jour est atteint, la raison le dit en euros et annonce la reprise pour demain."""
    base["today"], base["month"] = 10.4, 40.0
    state = budget_service.budget_state(NOW)
    assert state["budget_atteint"].startswith("plafond du jour atteint : 10.40 € dépensés sur 10.00 €")
    assert state["reste_du_jour_eur"] == 0 and state["reste_du_mois_eur"] == 35.0


def test_the_month_envelope_keeps_vany_share(base):
    """Les chaînes d'agents s'arrêtent quand il ne reste que la part de Vany : 75 € dépensés sur 100 €, avec 25 € gardés pour elle."""
    base["today"], base["month"] = 2.0, 75.0
    reason = budget_service.budget_state(NOW)["budget_atteint"]
    assert reason.startswith("enveloppe du mois atteinte : 75.00 € dépensés, 75.00 € permis aux agents (25.00 € gardés pour Vany)")
    assert "reprennent le 01/12/2026" in reason


def test_a_raised_cap_lets_passages_go_again(base):
    """Relever le plafond du jour débloque tout de suite, sans redémarrer : le réglage est relu à chaque décision."""
    base["today"], base["month"] = 10.4, 40.0
    assert budget_service.budget_state(NOW)["budget_atteint"] is not None
    budget_service.save_settings({"daily_budget_eur": 20.0}, "camille")
    assert budget_service.budget_state(NOW)["budget_atteint"] is None


def test_each_day_of_spending_is_converted_at_its_own_rate(base):
    """La dépense du mois additionne chaque jour converti à son taux : 10 $ à 1,20 $ (10 €) et 10 $ à 1,00 $ (12 €) font 22 € TTC, et 20 $."""
    base["today"], base["month"] = 10.0, 20.0
    base["rates"] = {FIRST_OF_MONTH: 1.20, TODAY: 1.00}
    state = budget_service.budget_state(NOW)
    assert (state["depense_du_mois_eur"], state["depense_du_mois_usd"]) == (22.0, 20.0)
    assert state["taux"] == "taux BCE du 19/11/2026 : 1 € = 1.0000 $"


def test_a_setting_written_in_dollars_is_read_in_euros_at_the_rate_of_its_day(base):
    """Le plafond de 5 $ réglé le 20 novembre, avant les euros, se lit 5,56 € TTC au taux de ce jour-là (1,08 $)."""
    base["latest"] = {"services_after_etl": 1, "monthly_budget_usd": 400.0, "daily_budget_usd": 5.0,
                      "vany_reserve_usd": 25.0, "monthly_budget_eur": None, "daily_budget_eur": None,
                      "vany_reserve_eur": None, "changed_at": datetime(2026, 11, 20, 12, 58), "changed_by": "admin",
                      "reason": "plafond de test remis à 5 $"}
    base["rates"] = {date(2026, 11, 20): 1.08}
    assert budget_service.budget_state(NOW)["plafond_du_jour_eur"] == 5.56


def test_without_any_known_rate_passages_wait_and_the_etl_still_reads_its_setting(base):
    """Sans aucun taux de la BCE, la dépense ne se compte pas en euros : les passages attendent, mais la fin de l'ETL lit toujours son réglage."""
    budget_service.save_settings({"services_after_etl": False}, "camille")
    base["latest"].update({"monthly_budget_eur": None, "daily_budget_eur": None, "vany_reserve_eur": None})
    base["rates"] = None
    assert budget_service.load_settings()["services_after_etl"] is False
    state = budget_service.budget_state(NOW)
    assert state["budget_atteint"].startswith("taux du dollar inconnu")
    assert state["plafond_du_jour_eur"] is None and state["depense_du_jour_eur"] is None


def test_without_any_known_rate_nothing_is_written(base):
    """Sans aucun taux de la BCE, un changement de montant est refusé : rien n'est écrit en dollars au hasard."""
    base["rates"] = None
    with pytest.raises(RateUnavailable):
        budget_service.save_settings({"daily_budget_eur": 6.0}, "camille")
    assert base["inserted"] == []


def test_the_next_month_of_december_is_january():
    """L'enveloppe de décembre repart le 1er janvier de l'année suivante."""
    assert budget_service.next_month(datetime(2026, 12, 31)) == datetime(2027, 1, 1)


def test_the_reason_of_a_change_is_kept_with_it(base):
    """La raison libre que l'admin donne à un changement est gardée avec lui, et rendue avec le réglage."""
    state = budget_service.save_settings({"daily_budget_eur": 0.0}, "camille", "test du budget atteint")
    assert state["raison_du_changement"] == "test du budget atteint" and state["budget_atteint"] is not None


def test_what_is_left_adds_up_with_what_is_spent(base):
    """Dépensé et restant s'additionnent au centime près : 2,73 € dépensés sur 10 € laissent 7,27 € (essai du 19 novembre, où 2,725 donnait 7,28)."""
    base["today"], base["month"] = 2.725, 40.0
    state = budget_service.budget_state(NOW)
    assert state["depense_du_jour_eur"] + state["reste_du_jour_eur"] == pytest.approx(10.0)
