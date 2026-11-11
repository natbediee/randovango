from dataclasses import replace
from datetime import date
from unittest.mock import MagicMock

import pytest

from agents.find_restaurants import RESTAURANTS
from services import service_store
from services.service_store import commune_of_address, compact_name, is_town_hall, page_accepted, page_date, parse_months, review_reason


def test_spaces_do_not_make_two_places():
    """« Ti Madeo » et « Ti Mad Eo » sont le même nom."""
    assert compact_name("Ti Madeo") == compact_name("Ti Mad Eo")


def test_town_hall_is_recognised():
    """Le site d'une mairie est reconnu à son domaine, pas un site qui contient seulement le nom de la commune."""
    assert is_town_hall("https://plougonvelin.fr/manger/ti-madeo.html", "Plougonvelin")
    assert is_town_hall("https://www.mairie-lanildut.fr/restaurants", "Plougonvelin")
    assert not is_town_hall("https://www.lacabaneplougonvelin.com/", "Plougonvelin")
    assert not is_town_hall("https://www.crozon-tourisme.bzh/restaurant/chez-germaine/", "Crozon")
    assert not is_town_hall("https://www.iroise-bretagne.bzh/restaurant/spiaggia/", "Plougonvelin")


def test_a_town_hall_page_is_not_a_proof():
    """La page d'une mairie ne prouve pas un restaurant."""
    page = {"verdict": "ok", "type_page": "office_tourisme", "url": "https://plougonvelin.fr/kan-ar-mor.html"}
    assert not page_accepted(page, commune="Plougonvelin")
    assert not page_accepted({"verdict": "ok", "type_page": "mairie", "url": "https://exemple.fr"})


def test_an_aggregator_is_never_a_proof():
    """Un agrégateur ne prouve jamais un service."""
    assert not page_accepted({"verdict": "ok", "type_page": "agregateur", "url": "https://exemple.fr"})


def test_a_registry_alert_sends_the_place_to_review_even_with_a_page():
    """Une alerte du registre ou une position introuvable donnent une raison de relecture ; sinon aucune."""
    assert "liquidation" in review_reason({"alerte_registre": "liquidation judiciaire"}, (48, -4))
    assert review_reason({}, None) == "position introuvable"
    assert review_reason({}, (48, -4)) is None


def test_a_place_without_an_accepted_page_is_not_kept(monkeypatch):
    """Un restaurant sans page acceptée ni registre est écarté : rien n'est créé ni signalé."""
    connection = MagicMock()
    monkeypatch.setattr(service_store.MySQLUtils, "connect", lambda: connection)
    monkeypatch.setattr(service_store.MySQLUtils, "disconnect", lambda *args: None)
    monkeypatch.setattr(service_store, "get_or_create_source", lambda cursor, name: 8)
    monkeypatch.setattr(service_store, "known_services", lambda cursor, city, services: [])
    monkeypatch.setattr(service_store, "_position", lambda city, address: (48.3, -4.7))
    monkeypatch.setattr(service_store, "create_poi", MagicMock(side_effect=AssertionError("ligne créée")))
    monkeypatch.setattr(service_store, "save_signal", MagicMock(side_effect=AssertionError("signal créé")))
    row = {"nom": "Le Nom Seul", "adresse": None, "alerte_registre": None,
           "pages": [{"url": "https://tripadvisor.fr/x", "type_page": "agregateur", "verdict": "site_exclu"}]}
    summary = service_store.save_commune(RESTAURANTS, {"name": "Plougonvelin"}, {"restaurants": [row]}, 8, "modele")
    assert summary == {"fiches": 0, "a_confirmer": 0, "sans_page": 1, "liquidation": 0}
    connection.commit.assert_called_once()


def test_parse_months_reads_a_range():
    """« avril à septembre » donne les mois d'ouverture."""
    assert parse_months("avril à septembre") == [3, 4, 5, 6, 7, 8]


def test_parse_months_crosses_the_new_year():
    """Une saison qui passe le nouvel an est lue dans l'ordre."""
    assert parse_months("novembre à février") == [10, 11, 0, 1]


def test_parse_months_refuses_anything_else():
    """Un texte qui n'est pas de la forme « mois à mois » ne donne aucun mois."""
    assert parse_months("horaires donnés pour l'été") == []
    assert parse_months(None) == []


def test_page_date_keeps_the_first_of_the_month():
    """Une date « année-mois » devient le premier jour du mois."""
    assert page_date("2026-07") == date(2026, 7, 1)


def test_page_date_refuses_what_is_not_a_date():
    """Ce qui n'est pas une date n'en devient pas une."""
    assert page_date("été 2026") is None
    assert page_date("2026-13") is None
    assert page_date(None) is None


def test_page_accepted_follows_the_code_verdict():
    """Une page est acceptée selon le verdict du contrôle fait par le code."""
    assert page_accepted({"verdict": "ok", "type_page": "site"})
    assert not page_accepted({"verdict": "nom_absent", "type_page": "site"})
    assert not page_accepted({"verdict": "a_valider_social", "type_page": "facebook"})


def test_a_social_page_is_never_a_proof():
    """Une page Facebook ou Instagram ne prouve jamais un service, quel que soit le type annoncé."""
    assert not page_accepted({"verdict": "ok", "type_page": "facebook", "url": "https://www.facebook.com/x"})
    assert not page_accepted({"verdict": "ok_rebond", "type_page": "instagram", "url": "https://www.instagram.com/x"})
    assert not page_accepted({"verdict": "ok", "type_page": "site", "url": "https://fr-fr.facebook.com/x"})
    assert page_accepted({"verdict": "ok", "type_page": "site", "url": "https://facebook-du-port.fr/"})


def test_article_must_be_dated_and_recent():
    """Un article de presse doit être daté et avoir moins de 18 mois."""
    today = date(2026, 11, 3)
    page = {"verdict": "ok", "type_page": "presse"}
    assert page_accepted({**page, "date_page": "2026-07"}, today)
    assert not page_accepted({**page, "date_page": None}, today)
    assert not page_accepted({**page, "date_page": "2024-07"}, today)


def test_commune_comes_from_the_address_or_the_search():
    """La commune vient de l'adresse du lieu, sinon de la commune cherchée."""
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

    def fetchall(self):
        return []      # aucune correction humaine (service_store.human_fields)

    def close(self):
        pass


def test_the_agent_season_is_saved():
    """La saison contrôlée de l'agent est enregistrée avec ses mois."""
    cursor = _SeasonCursor(decided=False)
    service_store._save_season(cursor, 1, {"saisonnier": True, "mois_ouverture": "avril à septembre"})
    assert cursor.updates == [("confirmee", "[3, 4, 5, 6, 7, 8]", 1)]


def test_a_human_season_decision_prevails_over_the_agent():
    """Une saison décidée par un humain n'est pas remplacée par celle de l'agent."""
    cursor = _SeasonCursor(decided=True)
    service_store._save_season(cursor, 1, {"saisonnier": True, "mois_ouverture": "mars à novembre"})
    assert cursor.updates == []


def test_a_season_no_longer_proved_is_cleared():
    """Une saison qui n'est plus prouvée est effacée."""
    cursor = _SeasonCursor(decided=False)
    service_store._save_season(cursor, 1, {"saisonnier": False})
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
    monkeypatch.setattr(service_store.MySQLUtils, "connect", staticmethod(lambda: calls["connection"]))
    monkeypatch.setattr(service_store.MySQLUtils, "disconnect", staticmethod(lambda connection: None))
    monkeypatch.setattr(service_store, "get_or_create_source", lambda cursor, name: 1)
    monkeypatch.setattr(service_store, "known_services", lambda cursor, city, services: list(known))
    monkeypatch.setattr(service_store, "_position", lambda city, address: (48.3, -4.7))
    monkeypatch.setattr(service_store, "flag", lambda category, cursor, row, position, city, known, source, reason, detail, link=None: calls["flag"].append(reason))
    monkeypatch.setattr(service_store, "create_poi", lambda category, cursor, row, position, city, source, masked: 99)
    monkeypatch.setattr(service_store, "save_sheet", lambda category, cursor, poi_id, row, version, model: calls["sheet"].append(poi_id))
    monkeypatch.setattr(service_store, "_save_proofs", lambda cursor, poi_id, pages: None)
    # Un réglage de test : le lieu connu est le premier de la liste, sans passer par les règles de nom.
    category = replace(RESTAURANTS, find_known=lambda row, position, city, known: known[0] if known else None)
    return service_store.save_commune(category, CITY, {"restaurants": [row]}, 7, "modele"), calls


PAGE = {"url": "https://riboul.fr", "type_page": "site", "verdict": "ok"}


def test_an_accepted_page_makes_a_sheet(monkeypatch):
    """Une page acceptée donne une fiche, et la transaction est validée."""
    summary, calls = _save(monkeypatch, {"nom": "Riboul", "pages": [PAGE]})
    assert summary == {"fiches": 1, "a_confirmer": 0, "sans_page": 0, "liquidation": 0} and calls["sheet"] == [99] and calls["connection"].committed


def test_the_link_shown_is_the_own_site_when_there_is_one(monkeypatch):
    """Le lien gardé est le site du restaurant quand il en a un, plutôt que la page de l'office de tourisme."""
    row = {"nom": "Riboul", "pages": [{"url": "https://iroise-bretagne.bzh/riboul", "type_page": "office_tourisme", "verdict": "ok"}, PAGE]}
    _save(monkeypatch, row)
    created = []
    monkeypatch.setattr(service_store, "create_poi", lambda category, cursor, row, position, city, source, masked: created.append(row["lien"]) or 99)
    service_store.save_commune(RESTAURANTS, CITY, {"restaurants": [row]}, 9, "modele")
    assert created == ["https://riboul.fr"]


def test_the_register_is_enough_to_keep_a_place_without_a_page(monkeypatch):
    """Le registre suffit à garder un restaurant sans page acceptée, alors sans lien."""
    created = []
    row = {"nom": "Café Konk", "au_registre": True, "pages": [{"url": "https://www.facebook.com/x", "type_page": "facebook", "verdict": "a_valider_social"}]}
    _save(monkeypatch, row)
    monkeypatch.setattr(service_store, "create_poi", lambda category, cursor, row, position, city, source, masked: created.append(row["lien"]) or 99)
    summary = service_store.save_commune(RESTAURANTS, CITY, {"restaurants": [row]}, 9, "modele")
    assert summary["fiches"] == 1 and created == [None]


def test_a_liquidation_removes_the_place_without_review(monkeypatch):
    """Une liquidation judiciaire écarte le restaurant sans relecture."""
    summary, calls = _save(monkeypatch, {"nom": "Le Plez'hir", "au_registre": True, "pages": [PAGE], "alerte_registre": "Ouverture d'une liquidation judiciaire"})
    assert summary["liquidation"] == 1 and summary["a_confirmer"] == 0 and calls["sheet"] == [] and calls["flag"] == []


def test_an_old_link_stays_when_no_page_was_accepted():
    """L'ancien lien reste quand aucune page n'a été acceptée."""
    cursor = MagicMock()
    cursor.fetchone.return_value = None
    service_store._update_poi(cursor, {"id": 5, "name": "A", "url": "https://a.fr"}, {"lien": None, "adresse": "1 place"}, None)
    assert "url" not in cursor.execute.call_args[0][0]


def test_an_old_facebook_link_gives_way_to_the_accepted_page():
    """Un ancien lien Facebook laisse la place à la page acceptée."""
    cursor = MagicMock()
    cursor.fetchone.return_value = None
    poi = {"id": 5, "name": "La Ria", "url": "https://www.facebook.com/laria29/"}
    service_store._update_poi(cursor, poi, {"lien": "https://www.iroise-bretagne.bzh/restaurant/la-ria/", "adresse": "1 place"}, None)
    assert "https://www.iroise-bretagne.bzh/restaurant/la-ria/" in cursor.execute.call_args[0][1]


def test_a_registry_alert_makes_no_sheet_even_with_a_page(monkeypatch):
    """Une alerte du registre envoie le restaurant en relecture, même avec une page acceptée."""
    summary, calls = _save(monkeypatch, {"nom": "Kan Ar Mor", "pages": [PAGE], "alerte_registre": "enseigne fermée"})
    assert summary["a_confirmer"] == 1 and summary["fiches"] == 0 and calls["sheet"] == []
    assert calls["flag"] == ["registre : enseigne fermée"]


def test_a_place_masked_by_a_human_is_left_alone(monkeypatch):
    """Un service masqué par un humain est laissé tel quel."""
    summary, calls = _save(monkeypatch, {"nom": "La Marina", "pages": [PAGE]}, known=[{"id": 5, "masque": 1}])
    assert summary == {"fiches": 0, "a_confirmer": 0, "sans_page": 0, "liquidation": 0} and calls["sheet"] == [] and calls["flag"] == []


def test_a_failure_writes_nothing(monkeypatch):
    """Une erreur pendant l'enregistrement annule toute la commune."""
    def broken(*args):
        raise RuntimeError("erreur")

    monkeypatch.setattr(service_store, "_position", broken)
    connection = _Connection()
    monkeypatch.setattr(service_store.MySQLUtils, "connect", staticmethod(lambda: connection))
    monkeypatch.setattr(service_store.MySQLUtils, "disconnect", staticmethod(lambda connection: None))
    monkeypatch.setattr(service_store, "get_or_create_source", lambda cursor, name: 1)
    monkeypatch.setattr(service_store, "known_services", lambda cursor, city, services: [])
    with pytest.raises(RuntimeError):
        service_store.save_commune(RESTAURANTS, CITY, {"restaurants": [{"nom": "X", "adresse": "1 quai", "pages": []}]}, 7, "modele")
    assert connection.rolled_back and not connection.committed


def test_a_place_the_agent_could_not_settle_waits_for_a_review(monkeypatch):
    """Un restaurant que l'agent n'a pas pu trancher attend une relecture, sans fiche."""
    reason = "preuve : l'agent n'a pas répondu à temps"
    summary, calls = _save(monkeypatch, {"nom": "Le Neuf", "a_relire": reason, "pages": []})
    assert summary == {"fiches": 0, "a_confirmer": 1, "sans_page": 0, "liquidation": 0} and calls["flag"] == [reason] and calls["sheet"] == []


TRISKELL = {"id": 1741, "name": "Le Triskell", "latitude": 48.4658, "longitude": -4.75981, "masque": 0}
PLOUDALMEZEAU = {"name": "Ploudalmézeau", "latitude": 48.5439, "longitude": -4.655}


def test_an_old_name_finds_a_known_place_only_at_the_address():
    """Un ancien nom ne retrouve un service connu qu'à son adresse, et jamais sans position."""
    row = {"nom": "Le Neuf", "ancien_nom": "Le Triskell"}
    assert service_store.find_known(row, (48.54071, -4.657928), PLOUDALMEZEAU, [TRISKELL]) is None
    assert service_store.find_known(row, (48.4659, -4.7598), PLOUDALMEZEAU, [TRISKELL]) == TRISKELL
    assert service_store.find_known(row, None, PLOUDALMEZEAU, [TRISKELL]) is None


def test_the_same_name_far_away_is_another_place():
    """Le même nom à 11 km désigne un autre restaurant ; à quelques mètres, c'est le même."""
    row = {"nom": "Le Triskell", "ancien_nom": None}
    assert service_store.find_known(row, (48.54071, -4.657928), PLOUDALMEZEAU, [TRISKELL]) is None
    assert service_store.find_known(row, (48.4659, -4.7598), PLOUDALMEZEAU, [TRISKELL]) == TRISKELL


def _known(name, address, latitude=48.27, longitude=-4.49):
    return {"id": 7, "name": name, "address": address, "latitude": latitude, "longitude": longitude, "masque": 0}


def test_the_same_table_under_a_longer_name_is_found_at_the_same_address():
    """Le même restaurant sous un nom plus long est retrouvé à la même adresse."""
    racines = _known("Racines", "82 Boulevard de la France Libre, 29160 Crozon")
    row = {"nom": "Restaurant Racines", "adresse": "82 boulevard de la France Libre, 29160 Crozon"}
    assert service_store.find_known(row, (48.0, -4.0), CITY, [racines]) == racines
    chaumine = _known("Crêperie La Chaumine", "4 Square de l'Abéric, 29830 Ploudalmézeau")
    row = {"nom": "La Chaumine Biligou", "adresse": "4 square de l'Aberic, 29830 Ploudalmézeau"}
    assert service_store.find_known(row, (48.0, -4.0), CITY, [chaumine]) == chaumine


def test_two_tables_sharing_an_address_stay_two():
    """Deux tables à la même adresse, sans nom proche, restent deux."""
    hostellerie = _known("L'Hostellerie", "1 place de la Mairie, 29217 Le Conquet")
    row = {"nom": "Bistrot 1954", "adresse": "1 place de la Mairie, 29217 Le Conquet"}
    assert service_store.find_known(row, (48.0, -4.0), CITY, [hostellerie]) is None


def test_a_place_without_street_number_is_found_by_its_name_and_position():
    """Sans numéro de rue, un restaurant est retrouvé par son nom et sa position, à 50 m près."""
    chateau = _known("La Crêperie du Château d'Eau", "Saint-Roch, 29830 Ploudalmézeau", 48.5300, -4.6600)
    row = {"nom": "Crêperie Le Château d'Eau", "adresse": "Saint-Roch, 29830 Ploudalmézeau"}
    assert service_store.find_known(row, (48.5300, -4.6600), CITY, [chateau]) == chateau
    assert service_store.find_known(row, (48.5400, -4.6600), CITY, [chateau]) is None


def test_the_measured_duplicates_are_found():
    """Les doublons relevés en base le 7 novembre 2026 sont reconnus."""
    pairs = [("Pizzeria Ty Forn", "Ty Forn", "17 T rue Pierre Brossolette, 29770 Plogoff"),
             ("Marmaris Kebab", "Marmaris", "42 place Napoléon III, 29200 Brest"),
             ("Restaurant de l'Oceania Quimper", "Restaurant Oceania", "17 rue du Poher, 29000 Quimper"),
             ("Restaurant du Camping Le Conleau", "Restaurant du Flower Camping Le Conleau", "188 avenue du Maréchal Juin, 56000 Vannes"),
             ("1930 Conleau", "Le 1930", "3 Allée des Frères Cadoret, 56000 Vannes")]
    for first, second, address in pairs:
        poi = _known(first, address)
        assert service_store.find_known({"nom": second, "adresse": address}, (48.0, -4.0), CITY, [poi]) == poi, second


def test_a_place_to_confirm_keeps_the_sheet_prepared_by_the_agent(monkeypatch):
    """Un restaurant à confirmer garde, dans son signal, la fiche préparée par l'agent."""
    details = []
    monkeypatch.setattr(service_store, "flag", lambda category, cursor, row, position, city, known, source, reason, detail, link=None: details.append(detail))
    _save_one = {"nom": "Le Neuf", "genre": "bar-tabac brasserie", "categorie": "brasserie", "pourquoi": "Le bistrot du bourg.",
                 "a_relire": "registre : débit de boissons, dit servir des repas par les recherches", "pages": []}
    calls = {"connection": _Connection()}
    monkeypatch.setattr(service_store.MySQLUtils, "connect", staticmethod(lambda: calls["connection"]))
    monkeypatch.setattr(service_store.MySQLUtils, "disconnect", staticmethod(lambda connection: None))
    monkeypatch.setattr(service_store, "get_or_create_source", lambda cursor, name: 1)
    monkeypatch.setattr(service_store, "known_services", lambda cursor, city, services: [])
    monkeypatch.setattr(service_store, "_position", lambda city, address: (48.3, -4.7))
    service_store.save_commune(RESTAURANTS, CITY, {"restaurants": [_save_one]}, 12, "modele")
    assert details[0]["fiche"]["genre"] == "bar-tabac brasserie" and details[0]["fiche"]["prompt_version"] == 12


def test_validating_a_place_without_a_prepared_sheet_is_refused():
    """Valider un restaurant sans fiche préparée est refusé."""
    with pytest.raises(ValueError):
        service_store.save_validated_sheet(RESTAURANTS, MagicMock(), 1, None)


def test_a_link_decided_by_a_human_is_never_replaced_by_the_agent():
    """Un lien décidé par un humain n'est jamais remplacé par celui de l'agent."""
    cursor = MagicMock()
    cursor.fetchone.return_value = (1,)
    service_store._update_poi(cursor, {"id": 5, "name": "Le Neuf", "url": "https://leneuf.fr"},
                                   {"lien": "https://iroise-bretagne.bzh/le-neuf", "adresse": "9 rue de Brest"}, None)
    assert "url" not in cursor.execute.call_args[0][0]
    assert service_store.RULE_AUTHOR in cursor.execute.call_args_list[0][0][1]


def test_a_name_decided_by_a_human_is_never_replaced_by_the_agent():
    """Un nom décidé par un humain n'est jamais remplacé par celui de l'agent."""
    cursor = MagicMock()
    cursor.fetchone.side_effect = [None, (1,)]
    service_store._update_poi(cursor, {"id": 5, "name": "Le Triskell", "url": None},
                                   {"lien": "https://leneuf.fr", "nom": "Le Neuf", "ancien_nom": "Le Triskell", "adresse": "9 rue de Brest"}, None)
    assert "name" not in cursor.execute.call_args[0][0] and "url" in cursor.execute.call_args[0][0]


CROZON_CITIES = [{"id": 15, "name": "Tal ar Groas", "commune": "Crozon", "insee": "29042"},
                 {"id": 16, "name": "Le Fret", "commune": "Crozon", "insee": "29042"},
                 {"id": 26, "name": "Trézien", "commune": "Plouarzel", "insee": "29177"},
                 {"id": 57, "name": "Crozon", "commune": "Crozon", "insee": "29042"},
                 {"id": 99, "name": "Nouvelle", "commune": None, "insee": None}]


def test_a_commune_is_searched_from_the_city_bearing_its_name():
    """Une commune est cherchée depuis la ville qui porte son nom, sinon depuis sa première ville."""
    assert [city["id"] for city in service_store.one_city_per_commune(CROZON_CITIES)] == [57, 26, 99]


@pytest.mark.parametrize("asked, searched", [("Le Fret", "Crozon"), ("Crozon", "Crozon"), ("Trézien", "Trézien"),
                                             ("Plouarzel", "Trézien"), ("Nouvelle", "Nouvelle"),
                                             ("Inconnue", None)])
def test_a_hamlet_is_searched_from_the_city_of_its_commune(monkeypatch, asked, searched):
    """Un hameau est cherché depuis la ville de sa commune ; une commune inconnue ne donne rien."""
    monkeypatch.setattr(service_store, "load_cities", lambda: CROZON_CITIES)
    city = service_store.load_city(asked)
    assert (city["name"] if city else None) == searched
