import json
import sys

import pytest

from agents import find_restaurants, find_service_links
from agents.find_restaurants import add_proofs, build_message, clean_name, has_accepted_page, merge_answers, registered_since
from api.routers.step4 import display_rank, keep_checked_restaurants


def _answer(restaurants=(), closed=(), set_aside=()):
    return {"restaurants": [_found(name, f"https://exemple.fr/{name}") for name in restaurants],
            "ecartes": [{"nom": name, "ferme": True} for name in closed] + [{"nom": name, "ferme": False} for name in set_aside]}


def _names(merged):
    return [row["nom"] for row in merged["restaurants"]]


def test_merge_keeps_each_restaurant_once():
    assert _names(merge_answers(_answer(["La Cabane"]), _answer(["la cabane", "La Balise"]))) == ["La Cabane", "La Balise"]


def test_a_place_found_by_any_search_is_kept():
    merged = merge_answers(_answer(["Spiaggia"]), _answer(["Riboul"]), _answer(["Ti Mad Eo"]), _answer(["La Balise"]))
    assert _names(merged) == ["Spiaggia", "Riboul", "Ti Mad Eo", "La Balise"]


def test_the_same_place_under_close_names_stays_once():
    merged = merge_answers(_answer(["Crêperie Riboul", "Spiaggia Restaurant", "Ti Madeo"]), _answer(["Riboul", "Spiaggia", "Ti Mad Eo"]))
    assert _names(merged) == ["Crêperie Riboul", "Spiaggia Restaurant", "Ti Madeo"]


def test_a_place_said_closed_by_another_search_goes_to_the_analyst():
    merged = merge_answers(_answer(["Crêperie de la plage", "Spiaggia"]), _answer(closed=["La Crêperie de la Plage"]))
    assert _names(merged) == ["Crêperie de la plage", "Spiaggia"]
    assert merged["restaurants"][0]["dit_ferme"]["nom"] == "La Crêperie de la Plage"
    assert "dit_ferme" not in merged["restaurants"][1]


def test_the_pages_of_every_search_are_kept():
    """L'Hostellerie : la première recherche ne citait que des sites exclus, la deuxième avait la page de l'office de tourisme."""
    first = {**_found("Hostellerie", "https://guide.michelin.com/hostellerie")}
    second = {**_found("Hostellerie", "https://iroise-bretagne.bzh/hostellerie"), "type_lien": "office_tourisme", "type_preuve": "office_tourisme"}
    merged = merge_answers({"restaurants": [first], "ecartes": []}, {"restaurants": [second], "ecartes": []})
    assert {page["url"] for page in merged["restaurants"][0]["pages_vues"]} == {first["lien"], second["lien"]}


def test_every_kept_page_is_controlled_once_with_its_citation(monkeypatch):
    monkeypatch.setattr(find_restaurants, "check_links_of", lambda row, place: [dict(link, verdict="ok") for link in row["liens"]])
    monkeypatch.setattr(find_restaurants, "citation_found", lambda citation, url: True)
    row = {"nom": "Riboul", "adresse": None, "pages_vues": [
        {"url": "https://a.fr", "type_page": "site"},
        {"url": "https://a.fr ", "type_page": "site", "citation": "Crêperie", "date_page": "2026-09"},
        {"url": "https://b.fr", "type_page": "office_tourisme"}]}
    pages = find_restaurants.control_row(row, "Plougonvelin")
    assert [page["url"] for page in pages] == ["https://a.fr", "https://b.fr"]
    assert pages[0]["citation"] == "Crêperie" and pages[0]["date_page"] == "2026-09" and "citation" not in pages[1]


def test_a_proof_controls_only_its_own_pages(monkeypatch):
    monkeypatch.setattr(find_restaurants, "check_links_of", lambda row, place: [dict(link, verdict="ok") for link in row["liens"]])
    row = {**_row(), "pages_vues": [{"url": "https://deja-vue.fr", "type_page": "site"}]}
    add_proofs(row, {"preuve_url": "https://nous.fr", "type_preuve": "site"}, "Plougonvelin")
    assert [page["url"] for page in row["pages"]] == ["https://annuaire.fr/nous", "https://nous.fr"]


def test_the_register_date_goes_by_name_and_keeps_the_oldest():
    register = {"actifs": [{"nom": "CAFE KONK", "actif_depuis": "2026-06-15"},
                           {"nom": "LES PANIERS DE MARIE.K", "actif_depuis": "2025-07-01"},
                           {"nom": "LES PANIERS DE MARIE.K", "actif_depuis": "2023-11-01"},
                           {"nom": None, "actif_depuis": "2026-01-01"}]}
    assert registered_since("Café Konk", register) == "2026-06-15"
    assert registered_since("Les Paniers de Marie.K", register) == "2023-11-01"
    assert registered_since("Autre nom", register) is None
    assert registered_since("Café Konk", None) is None


REGISTER = {"actifs": [{"nom": "CAFE KONK", "adresse": "18 RUE SAINT CHRISTOPHE 29217 LE CONQUET", "activite": "56.10A"},
                       {"nom": None, "adresse": "9 RUE LIEUTENANT JOURDEN 29217 LE CONQUET", "activite": "56.10A"},
                       {"nom": "SPIAGGIA", "adresse": "LIEUDIT LE TREZ HIR BOULEVARD DE LA MER 29217 PLOUGONVELIN", "activite": "56.10A"},
                       {"nom": "HOTEL DU LARGE", "adresse": "30 RUE SAINT MATHIEU 29217 PLOUGONVELIN", "activite": "55.10Z"}]}


def test_the_register_shows_a_restaurant_by_name_or_address():
    assert find_restaurants.in_register({"nom": "Café Konk", "adresse": None}, REGISTER)
    assert find_restaurants.in_register({"nom": "L'Armen", "adresse": "9 rue du Lieutenant Jourden, 29217 Le Conquet"}, REGISTER)


def test_a_bar_in_the_register_is_no_proof_of_a_restaurant():
    register = {"actifs": [{"nom": "L'UNIVERS", "adresse": "PLACE DE L'EGLISE 29217 PLOUGONVELIN", "activite": "56.30Z"}]}
    assert not find_restaurants.in_register({"nom": "L'Univers", "adresse": "Place de l'Église, 29217 Plougonvelin"}, register)


def test_a_street_without_number_or_a_hotel_shows_no_restaurant():
    assert not find_restaurants.in_register({"nom": "La Balise", "adresse": "Boulevard de la Mer, 29217 Plougonvelin"}, REGISTER)
    assert not find_restaurants.in_register({"nom": "L'Archipel", "adresse": "30 rue Saint-Mathieu, 29217 Plougonvelin"}, REGISTER)
    assert not find_restaurants.in_register({"nom": "Autre", "adresse": "18 rue du Port, 29217 Le Conquet"}, REGISTER)
    assert not find_restaurants.in_register({"nom": "Autre", "adresse": None}, None)


def test_a_place_only_said_closed_is_not_retained():
    assert _names(merge_answers(_answer(["Spiaggia"]), _answer(closed=["La Marina"]))) == ["Spiaggia"]


def test_a_place_set_aside_for_another_reason_stays():
    assert _names(merge_answers(_answer(["La Cabane"]), _answer(set_aside=["La Cabane"]))) == ["La Cabane"]


def test_name_loses_its_details():
    assert clean_name("Le Pêcheur (18 rue Saint-Yves)") == "Le Pêcheur"
    assert clean_name("L'Archipel – Hôtel du Large") == "L'Archipel"
    assert clean_name("L'Archipel - Hôtel du Large") == "L'Archipel"
    assert clean_name("Hostellerie de la Pointe Saint-Mathieu") == "Hostellerie de la Pointe Saint-Mathieu"
    assert clean_name("La Cabane") == "La Cabane"


def test_the_message_holds_the_register_only_when_there_is_one():
    city = {"name": "Le Conquet", "department": "Finistère"}
    assert "REGISTRE" not in build_message(city, None)
    assert "CAFE KONK" in build_message(city, {"actifs": [{"nom": "CAFE KONK"}]})


def _row():
    return {"nom": "NOUS", "adresse": None, "lien": "https://annuaire.fr/nous", "preuve_url": "https://annuaire.fr/nous",
            "pages": [{"url": "https://annuaire.fr/nous", "type_page": "agregateur", "verdict": "agregateur"}]}


def test_a_page_already_found_is_never_lost(monkeypatch):
    monkeypatch.setattr(find_restaurants, "control_row", lambda row, commune: [
        {"url": row["preuve_url"], "type_page": row["type_preuve"], "verdict": "ok"}])
    row = _row()
    add_proofs(row, {"preuve_url": "https://nous.fr", "type_preuve": "site", "adresse": "10 rue Saint-Yves"}, "Plougonvelin")
    assert [page["url"] for page in row["pages"]] == ["https://annuaire.fr/nous", "https://nous.fr"]
    assert row["adresse"] == "10 rue Saint-Yves" and has_accepted_page(row, "Plougonvelin")


def test_no_proof_found_changes_nothing(monkeypatch):
    row = _row()
    add_proofs(row, {}, "Plougonvelin")
    assert len(row["pages"]) == 1 and not has_accepted_page(row, "Plougonvelin")


def _poi(name, category, genre=None, address=None):
    return {"name": name, "service_category": category, "genre": genre, "address": address}


def test_restaurants_stay_while_the_commune_is_not_treated():
    pois = [_poi("Mary Stuart", "restaurant"), _poi("Toilettes", "toilets")]
    assert keep_checked_restaurants(pois) == pois


def test_only_checked_restaurants_remain_once_treated():
    kept = keep_checked_restaurants([_poi("La Cabane", "restaurant", "bistrot", "1 bd de la Mer, 29217 Plougonvelin"),
                                     _poi("Ancien", "restaurant", None, "2 bd de la Mer, 29217 Plougonvelin"),
                                     _poi("Sans adresse", "restaurant"),
                                     _poi("Toilettes", "toilets"), _poi("Café du port", "cafe")])
    assert [poi["name"] for poi in kept] == ["La Cabane", "Toilettes", "Café du port"]


def test_a_neighbour_with_sheets_does_not_hide_a_commune_not_yet_treated():
    kept = keep_checked_restaurants([_poi("La Cabane", "restaurant", "bistrot", "1 bd de la Mer, 29217 Plougonvelin"),
                                     _poi("La Cormorandière", "restaurant", None, "Place Henri Gestin, 29280 Locmaria-Plouzané")])
    assert [poi["name"] for poi in kept] == ["La Cabane", "La Cormorandière"]


def test_the_commune_sheets_come_first_then_the_nearest():
    pois = [{"name": "Café", "genre": None, "address": None, "distance_km": 1},
            {"name": "Voisin", "genre": "x", "address": "1 rue, 29217 Le Conquet", "distance_km": 3},
            {"name": "Hostellerie", "genre": "x", "address": "7 place, 29217 Plougonvelin", "distance_km": 5.2}]
    pois.sort(key=lambda poi: display_rank(poi, "Plougonvelin"))
    assert [poi["name"] for poi in pois] == ["Hostellerie", "Café", "Voisin"]


def _found(name, url):
    return {"nom": name, "genre": "x", "adresse": None, "ancien_nom": None, "pourquoi": "p", "lien": url, "type_lien": "agregateur",
            "preuve_url": url, "type_preuve": "agregateur", "preuve_citation": None, "preuve_date": None}


class _Agent:
    """Répond selon le schéma demandé, comme les trois agents de la chaîne."""
    last_run = {}

    def __init__(self, fail_on_analysis=False):
        self.fail_on_analysis = fail_on_analysis

    def complete_json(self, system, message, schema):
        if "restaurants" in schema["properties"]:
            return {"restaurants": [_found("NOUS", "https://tripadvisor.fr/nous"), {**_found("Riboul", "https://riboul.fr"), "type_lien": "site", "type_preuve": "site"},
                                    _found("La Vinotière", "https://vinotiere.fr")], "ecartes": []}
        if "preuve_url" in schema["properties"]["lieux"]["items"]["properties"]:
            return {"lieux": [{"numero": 1, "preuve_url": "https://nous.fr", "type_preuve": "site", "adresse": "10 rue Saint-Yves"}]}
        if self.fail_on_analysis:
            raise RuntimeError("quota")
        return {"lieux": [{"numero": 1, "ferme": False}, {"numero": 2, "ferme": False, "adresse": "2 bd de la Mer"},
                          {"numero": 3, "ferme": False, "pas_un_restaurant": True}]}


CITY = {"name": "Plougonvelin", "department": "Finistère", "latitude": 48.3, "longitude": -4.7}


def _chain(monkeypatch, tmp_path, agent, registered="AUTRE LIEU"):
    monkeypatch.setattr(find_restaurants, "TRACE_DIR", tmp_path)
    monkeypatch.setattr(find_restaurants, "make_llm_service", lambda name: agent)
    monkeypatch.setattr(find_restaurants.analyze_restaurants, "make_llm_service", lambda name: agent)
    monkeypatch.setattr(find_restaurants.api_registre, "load_register", lambda city: {"actifs": [{"nom": registered, "activite": "56.10A"}]})
    monkeypatch.setattr(find_service_links, "read_page", lambda url: {
        "statut": 200, "final": url, "texte": "nous riboul la vinotiere plougonvelin " + "x " * 200, "brut": ""})


def test_the_chain_keeps_found_pages_and_looks_for_the_missing_proof(monkeypatch, tmp_path):
    """Le cas du pilote : une page acceptée reste, l'analyste ne cherche que pour NOUS, La Vinotière sort."""
    agent = _Agent()
    _chain(monkeypatch, tmp_path, agent)
    answer = find_restaurants.search_commune(CITY)
    by_name = {row["nom"]: row for row in answer["restaurants"]}
    assert set(by_name) == {"NOUS", "Riboul"}
    assert [page["url"] for page in by_name["NOUS"]["pages"]] == ["https://tripadvisor.fr/nous", "https://nous.fr"]
    assert has_accepted_page(by_name["NOUS"], "Plougonvelin") and by_name["NOUS"]["adresse"] == "10 rue Saint-Yves"
    trace = json.loads(next(tmp_path.iterdir()).read_text())
    assert trace["registre"] and [row["nom"] for row in trace["preuves"]] == ["NOUS"]


def test_a_place_in_the_register_needs_no_proof_search(monkeypatch, tmp_path):
    _chain(monkeypatch, tmp_path, _Agent(), registered="NOUS")
    answer = find_restaurants.search_commune(CITY)
    by_name = {row["nom"]: row for row in answer["restaurants"]}
    assert by_name["NOUS"]["au_registre"] and not by_name["Riboul"]["au_registre"]
    trace = json.loads(next(tmp_path.iterdir()).read_text())
    assert "preuves" not in trace


def test_what_was_paid_stays_readable_when_a_step_fails(monkeypatch, tmp_path):
    _chain(monkeypatch, tmp_path, _Agent(fail_on_analysis=True))
    with pytest.raises(RuntimeError):
        find_restaurants.search_commune(CITY)
    trace = json.loads(next(tmp_path.iterdir()).read_text())
    assert len(trace["recherches"]) == 4 and "final" not in trace


def test_the_trial_mode_writes_nothing_in_the_database(monkeypatch):
    saved = []
    monkeypatch.setattr(sys, "argv", ["find_restaurants", "--ville", "Plougonvelin", "--essai"])
    monkeypatch.setattr(find_restaurants.restaurant_service, "load_city", lambda name: CITY)
    monkeypatch.setattr(find_restaurants.restaurant_service, "save_commune", lambda *args: saved.append(args))
    monkeypatch.setattr(find_restaurants, "search_commune", lambda city: {"restaurants": [{"nom": "Riboul"}]})
    find_restaurants.main()
    assert saved == []


def test_control_row_puts_the_citation_on_the_proof_page(monkeypatch):
    monkeypatch.setattr(find_restaurants, "check_links_of", lambda row, place: [dict(link, verdict="ok") for link in row["liens"]])
    monkeypatch.setattr(find_restaurants, "citation_found", lambda citation, url: True)
    row = {**_found("Riboul", "https://riboul.fr"), "preuve_url": "https://iroise.bzh/riboul", "type_preuve": "office_tourisme",
           "preuve_citation": "Crêperie", "preuve_date": "2026-09"}
    pages = find_restaurants.control_row(row, "Plougonvelin")
    assert [page.get("citation") for page in pages] == [None, "Crêperie"] and pages[1]["date_page"] == "2026-09"
