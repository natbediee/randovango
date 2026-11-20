"""
Le coût des agents en euros : le taux de la BCE et la conversion (services/exchange_rate_service.py, issue #275).

Aucune base ni réseau : la table exchange_rates et le site de la BCE sont remplacés par des valeurs posées par chaque
test.
"""
from datetime import date, datetime

import pytest
import requests

from services import exchange_rate_service

# Un extrait du fichier de la BCE, sous sa vraie forme : un bloc par jour, une ligne par monnaie.
ECB_XML = """<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01" xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
  <gesmes:subject>Reference rates</gesmes:subject>
  <Cube>
    <Cube time="2026-11-20"><Cube currency="USD" rate="1.0812"/><Cube currency="JPY" rate="162.5"/></Cube>
    <Cube time="2026-11-19"><Cube currency="JPY" rate="161.9"/><Cube currency="USD" rate="1.0790"/></Cube>
  </Cube>
</gesmes:Envelope>"""

FRIDAY = {"rate_date": date(2026, 11, 20), "usd_per_eur": 1.08}


class FakeResponse:
    """Une réponse du site de la BCE, telle que requests la rend."""
    text = ECB_XML

    def raise_for_status(self):
        pass


@pytest.fixture
def base(monkeypatch):
    """La table exchange_rates (taux par jour, dernière lecture), les écritures, et les appels au site de la BCE."""
    state = {"rates": {}, "last_fetch": None, "saved": [], "downloads": 0}
    store = exchange_rate_service.exchange_rate_store

    def rate_on_or_before(day):
        days = [known for known in state["rates"] if known <= day]
        return {"rate_date": max(days), "usd_per_eur": state["rates"][max(days)]} if days else None

    def oldest_rate():
        return {"rate_date": min(state["rates"]), "usd_per_eur": state["rates"][min(state["rates"])]} if state["rates"] else None

    def download(url, timeout):
        state["downloads"] += 1
        return FakeResponse()

    monkeypatch.setattr(store, "rate_on_or_before", rate_on_or_before)
    monkeypatch.setattr(store, "oldest_rate", oldest_rate)
    monkeypatch.setattr(store, "last_fetch", lambda: state["last_fetch"])
    monkeypatch.setattr(store, "save_rates", lambda rates, fetched_at: state["saved"].append(rates))
    monkeypatch.setattr(exchange_rate_service.requests, "get", download)
    monkeypatch.setattr(exchange_rate_service, "_failed_on", None)
    return state


def test_only_the_dollar_rate_of_each_day_is_read_from_the_ecb_file():
    """Du fichier de la BCE, on ne garde que le taux du dollar de chaque jour, quelle que soit sa place dans le bloc."""
    assert exchange_rate_service.parse_usd_rates(ECB_XML) == {date(2026, 11, 20): 1.0812, date(2026, 11, 19): 1.0790}


def test_the_ecb_is_read_once_a_day_at_most(base):
    """Les taux déjà lus aujourd'hui ne sont pas redemandés à la BCE ; lus hier, ils le sont."""
    base["last_fetch"] = datetime(2026, 11, 20, 9, 0)
    exchange_rate_service.refresh_rates(date(2026, 11, 20))
    assert base["downloads"] == 0
    exchange_rate_service.refresh_rates(date(2026, 11, 21))
    assert base["downloads"] == 1 and base["saved"] == [{date(2026, 11, 20): 1.0812, date(2026, 11, 19): 1.0790}]


def test_an_unreachable_ecb_stops_nothing_and_is_not_asked_again_the_same_day(base, monkeypatch):
    """BCE injoignable : rien n'est écrit, aucune erreur ne remonte, et on ne la redemande pas avant le lendemain."""
    def unreachable(url, timeout):
        base["downloads"] += 1
        raise requests.ConnectionError("pas de réseau")

    monkeypatch.setattr(exchange_rate_service.requests, "get", unreachable)
    exchange_rate_service.refresh_rates(date(2026, 11, 20))
    exchange_rate_service.refresh_rates(date(2026, 11, 20))
    assert base["downloads"] == 1 and base["saved"] == []


def test_a_call_is_converted_at_the_rate_of_its_own_day(base):
    """Un appel du vendredi 20 novembre est converti au taux publié ce jour-là, sans mention de taux d'un autre jour."""
    base["last_fetch"] = datetime(2026, 11, 20, 17, 0)
    base["rates"] = {date(2026, 11, 19): 1.07, date(2026, 11, 20): 1.08}
    rate = exchange_rate_service.rate_for(date(2026, 11, 20))
    assert rate == {"usd_per_eur": 1.08, "rate_date": date(2026, 11, 20), "same_day": True}
    assert exchange_rate_service.rate_label(rate) == "taux BCE du 20/11/2026 : 1 € = 1.0800 $"


def test_a_weekend_call_takes_the_last_known_rate_and_says_so(base):
    """Un appel du dimanche 22 novembre prend le taux du vendredi, et le libellé dit que c'est le dernier connu."""
    base["last_fetch"] = datetime(2026, 11, 22, 8, 0)
    base["rates"] = {date(2026, 11, 20): 1.08}
    rate = exchange_rate_service.rate_for(date(2026, 11, 22))
    assert rate["rate_date"] == date(2026, 11, 20) and rate["same_day"] is False
    assert exchange_rate_service.rate_label(rate).endswith("(dernier connu)")


def test_a_call_older_than_every_known_rate_takes_the_oldest_one(base):
    """Un appel plus ancien que tous les taux gardés est converti au plus ancien, signalé comme taux d'un autre jour."""
    base["last_fetch"] = datetime(2026, 11, 20, 17, 0)
    base["rates"] = {date(2026, 11, 2): 1.09}
    rate = exchange_rate_service.rate_for(date(2026, 10, 30))
    assert rate["usd_per_eur"] == 1.09 and rate["same_day"] is False


def test_without_any_known_rate_no_euro_amount_is_made_up(base, monkeypatch):
    """Sans aucun taux en base et BCE injoignable, la conversion refuse au lieu d'inventer un montant en euros."""
    def too_slow(url, timeout):
        raise requests.Timeout("trop long")

    monkeypatch.setattr(exchange_rate_service.requests, "get", too_slow)
    with pytest.raises(exchange_rate_service.RateUnavailable):
        exchange_rate_service.rate_for(date(2026, 11, 20))


def test_dollars_become_euros_including_vat_and_back():
    """10 $ à 1,08 $ pour un euro font 11,11 € TTC (TVA de 20 %) ; 11,11 € TTC redonnent 10 $."""
    assert exchange_rate_service.usd_to_eur(10, FRIDAY) == 11.11
    assert exchange_rate_service.eur_to_usd(11.11, FRIDAY) == 10.0
