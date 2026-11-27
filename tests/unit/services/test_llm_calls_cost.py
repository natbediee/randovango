"""
Le coût des appels d'agents en euros, et ce qu'il vaut (services/llm_calls_service.py, issue #275).

Le taux de la BCE vient de tests/conftest.py (1,20 $ pour un euro, qui compense la TVA : un dollar fait un euro TTC),
sauf quand un test pose le sien.
"""
from datetime import date, datetime

from services import llm_calls_service
from services.exchange_rate_service import RateUnavailable


def call(cost_usd, engine="claude-code", day=19):
    """Un appel de llm_calls, tel que passage_store.load_calls le rend."""
    return {"cost_usd": cost_usd, "engine": engine, "called_at": datetime(2026, 11, day, 10)}


def test_the_cost_says_whether_it_is_a_real_expense_or_an_api_equivalent():
    """Un coût par l'API est une dépense réelle, un coût par l'abonnement un équivalent API, et un mélange le dit."""
    assert llm_calls_service.cost_nature({"api", "api-batch"}) == "dépense réelle"
    assert llm_calls_service.cost_nature({"claude-code"}) == "équivalent API, abonnement"
    assert llm_calls_service.cost_nature({"api", "claude-code"}) == "en partie réelle, en partie équivalent API"


def test_each_call_is_converted_at_the_rate_of_its_day(monkeypatch):
    """Les appels du 18 (1 $ à 1,20 $) et du 19 novembre (1 $ à 1,00 $) font 2,20 € TTC, avec le taux du dernier jour."""
    rates = {date(2026, 11, 18): 1.20, date(2026, 11, 19): 1.00}
    monkeypatch.setattr(llm_calls_service.exchange_rate_service, "rate_for",
                        lambda day: {"usd_per_eur": rates[day], "rate_date": day, "same_day": True})
    cost = llm_calls_service.calls_cost([call(1.0, day=18), call(1.0, day=19)])
    assert (cost["cout_usd"], cost["cout_eur"]) == (2.0, 2.2)
    assert cost["taux"] == "taux BCE du 19/11/2026 : 1 € = 1.0000 $"


def test_without_any_known_rate_the_dollars_stay_and_the_euros_are_unknown(monkeypatch):
    """Sans aucun taux de la BCE, le coût garde ses dollars, ses euros restent inconnus, et le taux dit pourquoi."""
    def no_rate(day):
        raise RateUnavailable("aucun taux de la BCE connu")

    monkeypatch.setattr(llm_calls_service.exchange_rate_service, "rate_for", no_rate)
    cost = llm_calls_service.calls_cost([call(0.5)])
    assert (cost["cout_usd"], cost["cout_eur"]) == (0.5, None) and cost["taux"].startswith("euros inconnus")


def test_a_category_without_calls_costs_nothing():
    """Une catégorie sans aucun appel (une chaîne gratuite, OSM par exemple) coûte 0 $ et 0 €, sans se dire réelle ni équivalent API."""
    cost = llm_calls_service.calls_cost([])
    assert (cost["cout_usd"], cost["cout_eur"], cost["nature_du_cout"]) == (0, 0, None)


def test_the_log_line_of_a_call_gives_dollars_euros_nature_and_rate():
    """La fin d'une ligne du journal d'un agent donne la durée, les dollars, les euros TTC, ce que vaut le coût et le taux."""
    text = llm_calls_service.run_cost_text({"duration_ms": 42_000, "cost_usd": 0.53, "engine": "api"})
    assert text.startswith("42 s, 0.53 $ ≈ 0.53 € TTC (dépense réelle ; taux BCE du ")


# --- Le jour de Paris (#299) ---

def test_a_call_just_after_midnight_in_paris_takes_the_rate_of_that_day(monkeypatch):
    """Un appel fait à 0 h 30 à Paris le 19 novembre (23 h 30 UTC le 18) se convertit au taux du 19, pas à celui du 18."""
    rates = {date(2026, 11, 18): 1.20, date(2026, 11, 19): 1.00}
    monkeypatch.setattr(llm_calls_service.exchange_rate_service, "rate_for",
                        lambda day: {"usd_per_eur": rates[day], "rate_date": day, "same_day": True})
    late = {"cost_usd": 1.0, "engine": "api", "called_at": datetime(2026, 11, 18, 23, 30)}
    assert llm_calls_service.calls_cost([late])["cout_eur"] == 1.2


def test_the_daily_report_cuts_the_days_at_midnight_in_paris():
    """Le bilan « jour » range les appels de 23 h UTC le 27 novembre au 28, le jour qu'il est à Paris, et va du plus récent au plus ancien."""
    def hour(day, hour, calls, cost):
        return {"jour_utc": date(2026, 11, day), "heure_utc": hour, "appels": calls, "echecs": 0, "cout_usd": cost,
                "duree_ms": 1000 * calls, "tokens_entree": 10 * calls, "tokens_sortie": calls}
    report = llm_calls_service.paris_days([hour(27, 22, 2, 0.5), hour(27, 23, 1, 0.25), hour(28, 8, 3, 1.0)])
    assert [(row["jour"], row["appels"], row["cout_usd"]) for row in report] == [
        (date(2026, 11, 28), 4, 1.25), (date(2026, 11, 27), 2, 0.5)]
    assert "jour_utc" not in report[0] and report[0]["duree_ms"] == 4000
