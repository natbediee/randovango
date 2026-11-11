from unittest.mock import MagicMock

import pytest

from agents import find_commerces
from agents.find_commerces import COMMERCES
from agents.find_restaurants import RESTAURANTS
from services import service_store


class _Connection:
    def __init__(self):
        self.committed = False

    def cursor(self):
        return MagicMock()

    def commit(self):
        self.committed = True

    def rollback(self):
        pass


CITY = {"id": 1, "name": "Plougonvelin", "latitude": 48.3, "longitude": -4.7}


def _save(monkeypatch, row, known=()):
    calls = {"flag": [], "sheet": [], "created": [], "connection": _Connection()}
    monkeypatch.setattr(service_store.MySQLUtils, "connect", staticmethod(lambda: calls["connection"]))
    monkeypatch.setattr(service_store.MySQLUtils, "disconnect", staticmethod(lambda connection: None))
    monkeypatch.setattr(service_store, "get_or_create_source", lambda cursor, name: 1)
    monkeypatch.setattr(service_store, "known_services", lambda cursor, city, services: list(known))
    monkeypatch.setattr(service_store, "_position", lambda city, address: (48.3, -4.7))
    monkeypatch.setattr(service_store, "find_known", lambda row, position, city, known: known[0] if known else None)
    monkeypatch.setattr(service_store, "flag", lambda category, cursor, row, position, city, known, source, reason, detail, link=None:
                        calls["flag"].append((reason, detail)))
    monkeypatch.setattr(service_store, "create_poi", lambda category, cursor, row, position, city, source, masked:
                        calls["created"].append(row["lien"]) or 99)
    monkeypatch.setattr(service_store, "_save_season", lambda cursor, poi_id, row: None)
    monkeypatch.setattr(service_store, "save_sheet", lambda category, cursor, poi_id, row, version, model: calls["sheet"].append(poi_id))
    monkeypatch.setattr(service_store, "_save_proofs", lambda cursor, poi_id, pages: None)
    return service_store.save_commune(COMMERCES, CITY, {"commerces": [row]}, 1, "modele"), calls


TOWN_HALL = {"url": "https://www.plougonvelin.fr/marche", "type_page": "mairie", "verdict": "ok"}


def test_a_market_proved_by_its_town_hall_makes_a_sheet(monkeypatch):
    """Un marché prouvé par la page de sa mairie a sa fiche, avec cette page comme lien."""
    summary, calls = _save(monkeypatch, {"nom": "Marché de Plougonvelin", "categorie": "marche", "pages": [TOWN_HALL]})
    assert summary["fiches"] == 1 and calls["created"] == ["https://www.plougonvelin.fr/marche"] and calls["connection"].committed


def test_a_bakery_is_not_proved_by_the_town_hall(monkeypatch):
    """Une boulangerie n'est pas prouvée par la page de la mairie."""
    summary, calls = _save(monkeypatch, {"nom": "Le Gall", "categorie": "boulangerie", "pages": [TOWN_HALL]})
    assert summary["sans_page"] == 1 and calls["sheet"] == []


def test_the_register_is_enough_to_keep_a_shop_without_a_page(monkeypatch):
    """Le registre suffit à garder un commerce sans page, alors sans lien."""
    summary, calls = _save(monkeypatch, {"nom": "Le Gall", "categorie": "boulangerie", "au_registre": True, "pages": []})
    assert summary["fiches"] == 1 and calls["created"] == [None]


def test_a_place_to_confirm_keeps_the_sheet_prepared_by_the_agent(monkeypatch):
    """Un commerce à confirmer garde, dans son signal, la fiche préparée par l'agent."""
    row = {"nom": "Ferme de Kerlouan", "genre": "vente à la ferme", "categorie": "producteur", "jours": None,
           "a_relire": "preuve : l'agent n'a pas répondu à temps", "pages": []}
    summary, calls = _save(monkeypatch, row)
    reason, detail = calls["flag"][0]
    assert summary["a_confirmer"] == 1 and detail["fiche"]["genre"] == "vente à la ferme" and detail["fiche"]["prompt_version"] == 1


def test_a_liquidation_removes_the_shop_without_review(monkeypatch):
    """Une liquidation judiciaire écarte le commerce sans relecture."""
    summary, calls = _save(monkeypatch, {"nom": "Le Gall", "au_registre": True, "pages": [],
                                         "alerte_registre": "Ouverture d'une liquidation judiciaire"})
    assert summary["liquidation"] == 1 and calls["flag"] == [] and calls["sheet"] == []


def test_a_new_shop_takes_the_osm_service_of_its_category(monkeypatch):
    """Un commerce créé par l'agent prend le service OSM de sa sous-catégorie."""
    linked = []
    monkeypatch.setattr(service_store, "insert_histo_poi", lambda cursor, poi_id, city: None)
    monkeypatch.setattr(service_store, "insert_service_and_link", lambda cursor, poi_id, service: linked.append(service))
    cursor = MagicMock(lastrowid=5)
    for categorie in ("boulangerie", "epicerie", "marche", "producteur"):
        service_store.create_poi(COMMERCES, cursor, {"nom": "X", "categorie": categorie}, None, CITY, 1, masked=False)
    assert linked == ["bakery", "convenience", "marketplace", "farm"]


def test_the_sheet_goes_to_the_commerces_table():
    """La fiche d'un commerce validé s'écrit dans la table commerces, avec les jours du marché."""
    cursor = MagicMock()
    service_store.save_validated_sheet(COMMERCES, cursor, 7, {"genre": "marché", "jours": "jeudi matin", "categorie": "marche",
                                                      "prompt_version": 1, "model": "modele"})
    sql, params = next(call[0] for call in cursor.execute.call_args_list if "INTO commerces" in call[0][0])
    assert params[0] == 7 and "jeudi matin" in params


def test_validating_a_shop_without_a_prepared_sheet_is_refused():
    """Valider un commerce sans fiche préparée est refusé."""
    with pytest.raises(ValueError):
        service_store.save_validated_sheet(COMMERCES, MagicMock(), 1, None)


def test_validating_a_shop_to_confirm_writes_its_sheet_in_the_commerces_table(monkeypatch):
    """Dans la supervision, confirmer un commerce écrit sa fiche avec le réglage des commerces."""
    from services import poi_review_service as review
    written = []
    monkeypatch.setattr(service_store, "save_validated_sheet", lambda category, cursor, poi_id, sheet: written.append((category.sheet_table, poi_id)))
    signal = {"id": 3, "poi_id": 8, "signal_type": "a_confirmer", "source": COMMERCES.source,
              "detail": {"raison": "position introuvable", "fiche": {"genre": "boulangerie"}}}
    cursor = MagicMock()
    cursor.fetchall.return_value = [signal]
    cursor.fetchone.return_value = {column: None for column in review.APPLIED_COLUMNS}
    review.decide_one(cursor, "confirmer", 8, "valider_pepite", "", "admin", None)
    assert written == [("commerces", 8)]


def test_the_register_is_read_with_the_codes_asked_for(monkeypatch):
    """Le registre est lu avec les codes d'activité demandés, sinon avec ceux de la restauration."""
    from etl.extract import api_registre
    asked = []
    monkeypatch.setattr(api_registre, "_get", lambda url, params: asked.append(params["activite_principale"]) or {"total_pages": 1, "results": []})
    api_registre.read_register("29190", ("10.71C", "47.29Z"))
    api_registre.read_register("29190")
    assert asked == ["10.71C,47.29Z", ",".join(api_registre.ACTIVITIES)]


def test_the_badge_follows_the_proof(monkeypatch):
    """Le badge « Vérifié » suit la preuve : oui avec une page acceptée, non avec le registre seul."""
    marks = []
    monkeypatch.setattr(service_store, "set_verified", lambda cursor, poi_id, verified: marks.append(verified))
    _save(monkeypatch, {"nom": "Marché de Plougonvelin", "categorie": "marche", "pages": [TOWN_HALL]})
    monkeypatch.setattr(service_store, "set_verified", lambda cursor, poi_id, verified: marks.append(verified))
    _save(monkeypatch, {"nom": "Lagadec, Vins et Boissons", "categorie": "epicerie", "au_registre": True, "pages": []})
    assert marks == [True, False]


def test_a_shop_validated_by_a_human_is_verified():
    """Un commerce validé par un humain est « Vérifié »."""
    cursor = MagicMock()
    service_store.save_validated_sheet(COMMERCES, cursor, 7, {"genre": "boulangerie", "prompt_version": 1, "model": "modele"})
    assert cursor.execute.call_args_list[-1][0] == ("UPDATE poi SET verifie = %s WHERE id = %s", (1, 7))


def test_the_short_name_finds_the_osm_line():
    """« Boulangerie Laot » retrouve le service « Laot » d'OSM par son nom court."""
    assert find_commerces.short_name("Boulangerie Laot") == "Laot"
    assert find_commerces.short_name("Boulangerie de la Plage") == "Plage"
    assert find_commerces.short_name("Laot") is None and find_commerces.short_name("Café Ty") is None
    laot = {"id": 92, "name": "Laot", "address": "16 Rue Pen ar Bed, 29217 Plougonvelin", "latitude": 48.34, "longitude": -4.72, "masque": 0}
    found = find_commerces.find_known({"nom": "Boulangerie Laot", "adresse": "15 rue Pen ar Bed"}, (48.34, -4.72), CITY, [laot])
    assert found == laot


def test_a_cafe_with_a_restaurant_sheet_is_not_saved(monkeypatch):
    """Un café qui a déjà une fiche restaurant n'est pas enregistré."""
    _save(monkeypatch, {"nom": "Le Neuf", "categorie": "cafe", "pages": [TOWN_HALL]})
    table = {"id": 5, "name": "Le Neuf", "address": "1 rue", "latitude": 48.3, "longitude": -4.7, "masque": 0}
    monkeypatch.setattr(service_store, "known_sheets", lambda cursor, city, sheet_table: [table])
    summary = service_store.save_commune(COMMERCES, CITY, {"commerces": [{"nom": "Le Neuf", "categorie": "cafe", "pages": [TOWN_HALL]}]}, 2, "modele")
    assert summary["deja_restaurant"] == 1 and summary["fiches"] == 0


def test_a_sheet_sent_back_to_review_leaves_the_display(monkeypatch):
    """Un commerce renvoyé en relecture perd sa fiche jusqu'à la décision."""
    signals = []
    monkeypatch.setattr(service_store, "save_signal", lambda cursor, poi_id, source, kind, detail: signals.append((poi_id, detail["raison"])))
    cursor = MagicMock()
    cursor.fetchone.return_value = None
    assert service_store.send_to_review(COMMERCES, cursor, 32499, "registre seul", {"fiche": {"genre": "boucherie"}})
    sqls = [call[0][0] for call in cursor.execute.call_args_list]
    assert any(sql.startswith("DELETE FROM commerces") for sql in sqls) and signals == [(32499, "registre seul")]


def test_a_place_validated_by_a_human_keeps_its_sheet(monkeypatch):
    """Un commerce déjà validé par un humain garde sa fiche et n'est pas signalé."""
    monkeypatch.setattr(service_store, "save_signal", lambda *args: pytest.fail("pas de signal"))
    cursor = MagicMock()
    cursor.fetchone.return_value = (1,)
    assert not service_store.send_to_review(COMMERCES, cursor, 32499, "registre seul", {})
    assert not any("DELETE" in call[0][0] for call in cursor.execute.call_args_list)


def test_a_possible_duplicate_goes_to_the_duplicates_queue(monkeypatch):
    """Un doublon vu par l'analyste à une autre adresse arrive dans la file « Doublons » de la supervision."""
    signals = []
    monkeypatch.setattr(service_store, "save_signal", lambda cursor, poi_id, source, kind, detail: signals.append((poi_id, kind, detail)))
    rows = [{"nom": "Fumaisons d'Iroise"}, {"nom": "Fumaison d'Iroise", "doublon_possible": {"nom": "Fumaisons d'Iroise", "adresse": "Rue W"}}]
    saved = {"Fumaisons d'Iroise": {"id": 1, "latitude": 48.3557, "longitude": -4.7689},
             "Fumaison d'Iroise": {"id": 2, "latitude": 48.3545, "longitude": -4.77803}}
    assert service_store.flag_possible_duplicates(COMMERCES, MagicMock(), rows, saved) == 1
    poi_id, kind, detail = signals[0]
    assert (poi_id, kind, detail["autre_id"]) == (2, "doublon_commerce", 1) and 600 < detail["distance_m"] < 800
    from services import poi_review_service as review
    card = review.build_card("doublons", {"id": 2, "name": "Fumaison d'Iroise"}, [{"id": 9, "signal_type": kind, "source": "agent_commerces", "detail": detail}])
    assert card["actions"][:2] == ["fusionner", "deux_lieux"] and "Fumaisons d'Iroise" in card["preuves"][0]["texte"]


def test_a_visible_twin_wins_over_a_masked_one():
    """Entre deux jumeaux, le service visible est choisi avant le service masqué."""
    masked = {"id": 1, "name": "Boulangerie Lemaire", "address": "1 rue", "latitude": 48.40, "longitude": -4.00, "masque": 1}
    visible = {**masked, "id": 2, "latitude": 48.40001, "masque": 0}
    row = {"nom": "Boulangerie Lemaire", "adresse": "1 rue"}
    assert find_commerces.find_known(row, (48.40, -4.00), CITY, [masked, visible])["id"] == 2
    assert find_commerces.find_known(row, (48.40, -4.00), CITY, [masked])["id"] == 1


def test_the_register_and_a_page_naming_the_shop_make_it_verified(monkeypatch):
    """Le registre au nom du commerce et une page qui le nomme, même un annuaire, donnent le badge « Vérifié »."""
    marks = []
    monkeypatch.setattr(service_store, "set_verified", lambda cursor, poi_id, verified: marks.append(verified))
    directory = {"url": "https://www.myboulange.fr/la-meule-de-pierre", "type_page": "agregateur", "verdict": "ok"}
    _save(monkeypatch, {"nom": "La Meule de Pierre", "categorie": "boulangerie", "au_registre": True,
                        "registre_depuis": "2024-01-18", "pages": [directory]})
    _save(monkeypatch, {"nom": "Le Gall", "categorie": "boulangerie", "au_registre": True, "pages": [directory]})
    assert marks == [True, False]


def test_a_text_corrected_by_a_human_survives_a_new_pass(monkeypatch):
    """Un texte corrigé par un humain dans la supervision survit à un nouveau passage."""
    monkeypatch.setattr(service_store, "human_fields", lambda cursor, poi_id: {"pourquoi", "url"})
    cursor = MagicMock()
    cursor.fetchone.return_value = ("Le texte corrigé dans la supervision",)
    service_store.save_sheet(COMMERCES, cursor, 7, {"genre": "boulangerie", "pourquoi": "Texte de l'agent", "categorie": "boulangerie"}, 2, "modele")
    params = next(call[0][1] for call in cursor.execute.call_args_list if "INTO commerces" in call[0][0])
    assert "Le texte corrigé dans la supervision" in params and "Texte de l'agent" not in params


def test_a_new_pass_leaves_the_place_fields_a_human_corrected(monkeypatch):
    """Un nouveau passage ne touche ni à l'adresse, ni à la position, ni à la saison qu'un humain a corrigées."""
    monkeypatch.setattr(service_store, "human_fields", lambda cursor, poi_id: {"address", "maps_url", "saison"})
    monkeypatch.setattr(service_store, "_decided_by_human", lambda cursor, poi_id, decisions: False)
    cursor = MagicMock()
    poi = {"id": 7, "name": "Le Gall"}
    service_store._update_poi(cursor, poi, {"adresse": "1 rue", "lien": "https://legall.fr"}, (48.3, -4.7))
    sql, params = cursor.execute.call_args_list[-1][0]
    assert sql == "UPDATE poi SET url = %s WHERE id = %s" and params == ("https://legall.fr", 7)
    cursor.reset_mock()
    cursor.fetchone.return_value = None
    service_store._save_season(cursor, 7, {"saisonnier": True, "mois_ouverture": "juillet à août"})
    assert not any("statut_saison" in call[0][0] for call in cursor.execute.call_args_list)


def test_an_alert_contradicted_by_an_active_line_at_the_same_name_and_address_is_cleared():
    """Une alerte contredite par une ligne active au même nom et à la même adresse est effacée ; une liquidation ne l'est jamais."""
    register = {"actifs": [{"nom": "A FLEUR D'EAU", "adresse": "25 QUAI DU GRAND PORT 29100 DOUARNENEZ", "activite": "56.10A",
                            "actif_depuis": "2025-05-15"}]}
    row = {"nom": "A Fleur d'Eau", "adresse": "25 quai du Grand Port, 29100 Douarnenez",
           "alerte_registre": "enseigne fermée le 2025-07-01, sans établissement actif du même nom"}
    other = {**row, "nom": "Au Vieux Logis", "alerte_registre": "autre nom actif à l'adresse : TMT 29"}
    liquidated = {**row, "alerte_registre": "Ouverture d'une liquidation judiciaire"}
    rows = [row, other, liquidated]
    service_store.clear_contradicted_alerts(RESTAURANTS, rows, register, "Douarnenez")
    assert row["alerte_registre"] is None and other["alerte_registre"] and liquidated["alerte_registre"]


def test_a_place_to_confirm_keeps_its_accepted_page(monkeypatch):
    """Un commerce à confirmer est créé masqué, avec sa page acceptée comme lien."""
    linked = []
    calls = {"connection": _Connection()}
    monkeypatch.setattr(service_store.MySQLUtils, "connect", staticmethod(lambda: calls["connection"]))
    monkeypatch.setattr(service_store.MySQLUtils, "disconnect", staticmethod(lambda connection: None))
    monkeypatch.setattr(service_store, "get_or_create_source", lambda cursor, name: 1)
    monkeypatch.setattr(service_store, "known_services", lambda cursor, city, services: [])
    monkeypatch.setattr(service_store, "known_sheets", lambda cursor, city, sheet_table: [])
    monkeypatch.setattr(service_store, "_position", lambda city, address: None)
    monkeypatch.setattr(service_store, "send_to_review", lambda category, cursor, poi_id, reason, detail: True)
    monkeypatch.setattr(service_store, "create_poi", lambda category, cursor, row, position, city, source, masked: linked.append((row["lien"], masked)) or 9)
    site = {"url": "https://www.legall.fr", "type_page": "site", "verdict": "ok"}
    summary = service_store.save_commune(COMMERCES, CITY, {"commerces": [{"nom": "Le Gall", "categorie": "boulangerie", "genre": "boulangerie",
                                                                  "lien": "https://facebook.com/legall", "pages": [site]}]}, 2, "modele")
    assert summary["a_confirmer"] == 1 and linked == [("https://www.legall.fr", True)]
