from datetime import date
from unittest.mock import MagicMock

import pytest

from services import restaurant_service
from services.restaurant_service import commune_of_address, compact_name, is_town_hall, page_accepted, page_date, parse_months, review_reason


def test_spaces_do_not_make_two_places():
    assert compact_name("Ti Madeo") == compact_name("Ti Mad Eo")


def test_town_hall_is_recognised():
    assert is_town_hall("https://plougonvelin.fr/manger/ti-madeo.html", "Plougonvelin")
    assert is_town_hall("https://www.mairie-lanildut.fr/restaurants", "Plougonvelin")
    assert not is_town_hall("https://www.lacabaneplougonvelin.com/", "Plougonvelin")
    assert not is_town_hall("https://www.crozon-tourisme.bzh/restaurant/chez-germaine/", "Crozon")
    assert not is_town_hall("https://www.iroise-bretagne.bzh/restaurant/spiaggia/", "Plougonvelin")


def test_a_town_hall_page_is_not_a_proof():
    page = {"verdict": "ok", "type_page": "office_tourisme", "url": "https://plougonvelin.fr/kan-ar-mor.html"}
    assert not page_accepted(page, commune="Plougonvelin")
    assert not page_accepted({"verdict": "ok", "type_page": "mairie", "url": "https://exemple.fr"})


def test_an_aggregator_is_never_a_proof():
    assert not page_accepted({"verdict": "ok", "type_page": "agregateur", "url": "https://exemple.fr"})


def test_a_registry_alert_sends_the_place_to_review_even_with_a_page():
    assert "liquidation" in review_reason({"alerte_registre": "liquidation judiciaire"}, (48, -4))
    assert review_reason({}, None) == "position introuvable"
    assert review_reason({}, (48, -4)) is None


def test_a_place_without_an_accepted_page_is_not_kept(monkeypatch):
    connection = MagicMock()
    monkeypatch.setattr(restaurant_service.MySQLUtils, "connect", lambda: connection)
    monkeypatch.setattr(restaurant_service.MySQLUtils, "disconnect", lambda *args: None)
    monkeypatch.setattr(restaurant_service, "get_or_create_source", lambda cursor, name: 8)
    monkeypatch.setattr(restaurant_service, "_known_restaurants", lambda cursor, city: [])
    monkeypatch.setattr(restaurant_service, "_position", lambda city, address: (48.3, -4.7))
    monkeypatch.setattr(restaurant_service, "_create_poi", MagicMock(side_effect=AssertionError("ligne créée")))
    monkeypatch.setattr(restaurant_service, "save_signal", MagicMock(side_effect=AssertionError("signal créé")))
    row = {"nom": "Le Nom Seul", "adresse": None, "alerte_registre": None,
           "pages": [{"url": "https://tripadvisor.fr/x", "type_page": "agregateur", "verdict": "site_exclu"}]}
    summary = restaurant_service.save_commune({"name": "Plougonvelin"}, {"restaurants": [row]}, 8, "modele")
    assert summary == {"fiches": 0, "a_confirmer": 0, "sans_page": 1}
    connection.commit.assert_called_once()


def test_parse_months_reads_a_range():
    assert parse_months("avril à septembre") == [3, 4, 5, 6, 7, 8]


def test_parse_months_crosses_the_new_year():
    assert parse_months("novembre à février") == [10, 11, 0, 1]


def test_parse_months_refuses_anything_else():
    assert parse_months("horaires donnés pour l'été") == []
    assert parse_months(None) == []


def test_page_date_keeps_the_first_of_the_month():
    assert page_date("2026-07") == date(2026, 7, 1)


def test_page_date_refuses_what_is_not_a_date():
    assert page_date("été 2026") is None
    assert page_date("2026-13") is None
    assert page_date(None) is None


def test_page_accepted_follows_the_code_verdict():
    assert page_accepted({"verdict": "ok", "type_page": "site"})
    assert not page_accepted({"verdict": "nom_absent", "type_page": "site"})
    assert not page_accepted({"verdict": "a_valider_social", "type_page": "facebook"})


def test_a_social_page_is_never_a_proof():
    assert not page_accepted({"verdict": "ok", "type_page": "facebook", "url": "https://www.facebook.com/x"})
    assert not page_accepted({"verdict": "ok_rebond", "type_page": "instagram", "url": "https://www.instagram.com/x"})
    assert not page_accepted({"verdict": "ok", "type_page": "site", "url": "https://fr-fr.facebook.com/x"})
    assert page_accepted({"verdict": "ok", "type_page": "site", "url": "https://facebook-du-port.fr/"})


def test_article_must_be_dated_and_recent():
    today = date(2026, 11, 3)
    page = {"verdict": "ok", "type_page": "presse"}
    assert page_accepted({**page, "date_page": "2026-07"}, today)
    assert not page_accepted({**page, "date_page": None}, today)
    assert not page_accepted({**page, "date_page": "2024-07"}, today)


def test_commune_comes_from_the_address_or_the_search():
    assert commune_of_address("7 place Saint-Tanguy, 29217 Plougonvelin", "Le Conquet") == ("Plougonvelin", "29217")
    assert commune_of_address(None, "Plougonvelin") == ("Plougonvelin", None)


class _SeasonCursor:
    def __init__(self, decided):
        self.decided, self.updates = decided, []

    def execute(self, sql, params=None):
        if sql.startswith("UPDATE"):
            self.updates.append(params)

    def fetchone(self):
        return (1,) if self.decided else None

    def close(self):
        pass


def test_the_agent_season_is_saved():
    cursor = _SeasonCursor(decided=False)
    restaurant_service._save_season(cursor, 1, {"saisonnier": True, "mois_ouverture": "avril à septembre"})
    assert cursor.updates == [("confirmee", "[3, 4, 5, 6, 7, 8]", 1)]


def test_a_human_season_decision_prevails_over_the_agent():
    cursor = _SeasonCursor(decided=True)
    restaurant_service._save_season(cursor, 1, {"saisonnier": True, "mois_ouverture": "mars à novembre"})
    assert cursor.updates == []


def test_a_season_no_longer_proved_is_cleared():
    cursor = _SeasonCursor(decided=False)
    restaurant_service._save_season(cursor, 1, {"saisonnier": False})
    assert cursor.updates == [(1,)]


class _Connection:
    def __init__(self):
        self.committed = self.rolled_back = False

    def cursor(self):
        return _SeasonCursor(decided=False)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


CITY = {"id": 1, "name": "Plougonvelin", "latitude": 48.3, "longitude": -4.7}


def _save(monkeypatch, row, known=()):
    calls = {"flag": [], "sheet": [], "connection": _Connection()}
    monkeypatch.setattr(restaurant_service.MySQLUtils, "connect", staticmethod(lambda: calls["connection"]))
    monkeypatch.setattr(restaurant_service.MySQLUtils, "disconnect", staticmethod(lambda connection: None))
    monkeypatch.setattr(restaurant_service, "get_or_create_source", lambda cursor, name: 1)
    monkeypatch.setattr(restaurant_service, "_known_restaurants", lambda cursor, city: list(known))
    monkeypatch.setattr(restaurant_service, "_position", lambda city, address: (48.3, -4.7))
    monkeypatch.setattr(restaurant_service, "_find_known", lambda row, position, city, known: known[0] if known else None)
    monkeypatch.setattr(restaurant_service, "_flag", lambda cursor, row, position, city, known, source, reason, detail: calls["flag"].append(reason))
    monkeypatch.setattr(restaurant_service, "_create_poi", lambda cursor, row, position, city, source, masked: 99)
    monkeypatch.setattr(restaurant_service, "_save_sheet", lambda cursor, poi_id, row, version, model: calls["sheet"].append(poi_id))
    monkeypatch.setattr(restaurant_service, "_save_proofs", lambda cursor, poi_id, pages: None)
    return restaurant_service.save_commune(CITY, {"restaurants": [row]}, 7, "modele"), calls


PAGE = {"url": "https://riboul.fr", "type_page": "site", "verdict": "ok"}


def test_an_accepted_page_makes_a_sheet(monkeypatch):
    summary, calls = _save(monkeypatch, {"nom": "Riboul", "pages": [PAGE]})
    assert summary == {"fiches": 1, "a_confirmer": 0, "sans_page": 0} and calls["sheet"] == [99] and calls["connection"].committed


def test_a_registry_alert_makes_no_sheet_even_with_a_page(monkeypatch):
    summary, calls = _save(monkeypatch, {"nom": "Kan Ar Mor", "pages": [PAGE], "alerte_registre": "liquidation judiciaire"})
    assert summary == {"fiches": 0, "a_confirmer": 1, "sans_page": 0} and calls["sheet"] == []
    assert calls["flag"] == ["registre : liquidation judiciaire"]


def test_a_place_masked_by_a_human_is_left_alone(monkeypatch):
    summary, calls = _save(monkeypatch, {"nom": "La Marina", "pages": [PAGE]}, known=[{"id": 5, "masque": 1}])
    assert summary == {"fiches": 0, "a_confirmer": 0, "sans_page": 0} and calls["sheet"] == [] and calls["flag"] == []


def test_a_failure_writes_nothing(monkeypatch):
    def broken(*args):
        raise RuntimeError("erreur")

    monkeypatch.setattr(restaurant_service, "_position", broken)
    connection = _Connection()
    monkeypatch.setattr(restaurant_service.MySQLUtils, "connect", staticmethod(lambda: connection))
    monkeypatch.setattr(restaurant_service.MySQLUtils, "disconnect", staticmethod(lambda connection: None))
    monkeypatch.setattr(restaurant_service, "get_or_create_source", lambda cursor, name: 1)
    monkeypatch.setattr(restaurant_service, "_known_restaurants", lambda cursor, city: [])
    with pytest.raises(RuntimeError):
        restaurant_service.save_commune(CITY, {"restaurants": [{"nom": "X", "adresse": "1 quai", "pages": []}]}, 7, "modele")
    assert connection.rolled_back and not connection.committed
