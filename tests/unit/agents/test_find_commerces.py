import json

import pytest

from agents import find_commerces, find_service_links
from agents.find_commerces import (has_accepted_page, in_register, merge_answers, register_for_agent, registered_since)
from services.commerce_service import place_key


def _found(name, url, categorie="boulangerie"):
    return {"nom": name, "genre": "boulangerie", "categorie": categorie, "adresse": None, "ancien_nom": None, "pourquoi": "",
            "lien": url, "type_lien": "agregateur", "preuve_url": url, "type_preuve": "agregateur",
            "preuve_citation": None, "preuve_date": None}


def _answer(shops=(), closed=()):
    return {"commerces": [_found(name, f"https://exemple.fr/{name}") for name in shops],
            "ecartes": [{"nom": name, "ferme": True} for name in closed]}


def test_the_shop_word_does_not_make_two_places():
    assert place_key("Boulangerie Le Gall") == place_key("Le Gall")
    assert place_key("Marché de Plougonvelin") == place_key("Plougonvelin")


def test_merge_keeps_each_shop_once_with_the_pages_of_every_search():
    merged = merge_answers(_answer(["Boulangerie Le Gall"]), _answer(["Le Gall", "Ty Krampouezh"]))
    assert [row["nom"] for row in merged["commerces"]] == ["Boulangerie Le Gall", "Ty Krampouezh"]
    assert len(merged["commerces"][0]["pages_vues"]) == 4


def test_a_shop_said_closed_by_another_search_goes_to_the_analyst():
    merged = merge_answers(_answer(["Le Gall"]), _answer(closed=["Boulangerie Le Gall"]))
    assert merged["commerces"][0]["dit_ferme"]["nom"] == "Boulangerie Le Gall"


REGISTER = {"actifs": [{"nom": "LE GALL", "adresse": "3 RUE DE LA MER 29217 PLOUGONVELIN", "activite": "10.71C",
                        "actif_depuis": "2025-12-01"},
                       {"nom": "PLOUGONVELIN", "adresse": "PLACE DU BOURG", "activite": "47.11C", "actif_depuis": "2001-01-01"}]}


def test_the_register_shows_a_shop_by_name_or_address():
    assert in_register({"nom": "Boulangerie Le Gall", "categorie": "boulangerie"}, REGISTER)
    assert in_register({"nom": "Autre nom", "adresse": "3 rue de la Mer", "categorie": "boulangerie"}, REGISTER)
    assert not in_register({"nom": "Ty Krampouezh", "categorie": "epicerie"}, REGISTER)


def test_a_market_is_never_in_the_register():
    market = {"nom": "Marché de Plougonvelin", "categorie": "marche"}
    assert not in_register(market, REGISTER) and registered_since(market, REGISTER) is None


def test_the_register_date_goes_by_name():
    assert registered_since({"nom": "Le Gall", "categorie": "boulangerie"}, REGISTER) == "2025-12-01"


def test_a_zone_reads_only_the_nearest_lines_of_the_register():
    register = {"actifs": [{"nom": "Près", "position": [48.30, -4.70]}, {"nom": "Loin", "position": [48.50, -4.70]},
                           {"nom": "Sans position"}]}
    zone = {"latitude": 48.30, "longitude": -4.70, "repere": "le port"}
    assert register_for_agent(register, zone) == {"actifs": [{"nom": "Près"}]}
    assert [line["nom"] for line in register_for_agent(register)["actifs"]] == ["Près", "Loin", "Sans position"]


def test_a_town_hall_page_proves_a_market_but_not_a_bakery():
    page = {"url": "https://www.plougonvelin.fr/marche", "type_page": "mairie", "verdict": "ok"}
    assert has_accepted_page({"categorie": "marche", "pages": [page]}, "Plougonvelin")
    assert not has_accepted_page({"categorie": "boulangerie", "pages": [page]}, "Plougonvelin")


class _Agent:
    """Répond selon le schéma demandé, comme les trois agents de la chaîne."""
    last_run = {}

    def __init__(self, fail_on_analysis=False):
        self.fail_on_analysis = fail_on_analysis

    def complete_json(self, system, message, schema):
        if "commerces" in schema["properties"]:
            return {"commerces": [_found("Le Gall", "https://pagesjaunes.fr/legall"),
                                  {**_found("Marché de Plougonvelin", "https://www.plougonvelin.fr/marche", "marche"), "type_lien": "mairie",
                                   "type_preuve": "mairie"},
                                  _found("Grossiste Iroise", "https://grossiste.fr")], "ecartes": []}
        if "preuve_url" in schema["properties"]["lieux"]["items"]["properties"]:
            return {"lieux": [{"numero": 1, "preuve_url": "https://legall.fr", "type_preuve": "site", "adresse": "3 rue de la Mer"}]}
        if self.fail_on_analysis:
            raise RuntimeError("quota")
        return {"lieux": [{"numero": 1, "ferme": False},
                          {"numero": 2, "ferme": False, "details": [{"champ": "jours", "valeur": "jeudi matin",
                                                                     "citation": "Le marché a lieu le jeudi matin sur la place.",
                                                                     "page": "https://www.plougonvelin.fr/marche", "type_page": "mairie"}]},
                          {"numero": 3, "ferme": False, "pas_un_commerce": True}]}


CITY = {"name": "Plougonvelin", "department": "Finistère", "latitude": 48.3, "longitude": -4.7}


def _chain(monkeypatch, tmp_path, agent, registered="AUTRE LIEU"):
    activities = []
    monkeypatch.setattr(find_commerces, "TRACE_DIR", tmp_path)
    monkeypatch.setattr(find_commerces, "make_llm_service", lambda name: agent)
    monkeypatch.setattr(find_commerces.analyze_commerces, "make_llm_service", lambda name: agent)
    monkeypatch.setattr(find_commerces.api_registre, "load_register",
                        lambda city, codes: activities.append(codes) or {"actifs": [{"nom": registered, "activite": "10.71C"}]})
    monkeypatch.setattr(find_service_links, "read_page", lambda url: {
        "statut": 200, "final": url, "texte": "le gall marche de plougonvelin le marche a lieu le jeudi matin sur la place "
                                              + "x " * 200, "brut": ""})
    return activities


def test_the_chain_proves_a_market_by_its_town_hall_and_looks_for_the_missing_proof(monkeypatch, tmp_path):
    activities = _chain(monkeypatch, tmp_path, _Agent())
    answer = find_commerces.search_commune(CITY)
    by_name = {row["nom"]: row for row in answer["commerces"]}
    assert set(by_name) == {"Le Gall", "Marché de Plougonvelin"}
    assert by_name["Marché de Plougonvelin"]["jours"] == "jeudi matin"
    assert by_name["Le Gall"]["adresse"] == "3 rue de la Mer"
    trace = json.loads(next(tmp_path.iterdir()).read_text())
    assert [row["nom"] for row in trace["preuves"]] == ["Le Gall"]
    assert activities == [find_commerces.REGISTER_ACTIVITIES] and "47.11D" not in activities[0]


def test_a_shop_in_the_register_needs_no_proof_search(monkeypatch, tmp_path):
    _chain(monkeypatch, tmp_path, _Agent(), registered="LE GALL")
    answer = find_commerces.search_commune(CITY)
    assert {row["nom"]: row["au_registre"] for row in answer["commerces"]} == {"Le Gall": True, "Marché de Plougonvelin": False}
    assert "preuves" not in json.loads(next(tmp_path.iterdir()).read_text())


def test_what_was_paid_stays_readable_when_a_step_fails(monkeypatch, tmp_path):
    _chain(monkeypatch, tmp_path, _Agent(fail_on_analysis=True))
    with pytest.raises(RuntimeError):
        find_commerces.search_commune(CITY)
    trace = json.loads(next(tmp_path.iterdir()).read_text())
    assert len(trace["recherches"]) == 5 and trace["version"] == find_commerces.COMMERCES_PROMPT_VERSION


def test_a_bar_line_proves_a_cafe_but_not_a_bakery():
    register = {"actifs": [{"nom": "LE PORT", "adresse": "1 QUAI DU PORT", "activite": "56.30Z", "actif_depuis": "2020-01-01"}]}
    assert in_register({"nom": "Le Port", "categorie": "cafe"}, register)
    assert not in_register({"nom": "Le Port", "categorie": "boulangerie"}, register)
    assert not in_register({"nom": "Le Gall", "categorie": "cafe"}, REGISTER)


def test_a_place_held_by_the_register_alone_waits_for_a_review():
    register = {"actifs": [{"nom": "SRB (SERVICE DE REMPLACEMENT BOUCHER )", "adresse": "4 B RUE SAINT MATHIEU 29217 PLOUGONVELIN",
                            "activite": "47.22Z", "actif_depuis": "2026-02-01"}]}
    row = {"nom": "Boucherie Leonetti-Degavre", "categorie": "producteur", "adresse": "4 B rue Saint-Mathieu, 29217 Plougonvelin",
           "pages": [{"url": "https://annuaire.fr/x", "type_page": "agregateur", "verdict": "nom_absent"}]}
    reason = find_commerces.register_only_reason(row, register, "Plougonvelin")
    assert reason.startswith(find_commerces.REGISTER_ONLY) and "SRB" in reason and "2026-02-01" in reason
    named = {**row, "pages": [{"url": "https://annuaire.fr/x", "type_page": "agregateur", "verdict": "ok"}]}
    assert find_commerces.register_only_reason(named, register, "Plougonvelin") is None


def test_the_cafe_search_is_the_only_one_asked_for_cafes():
    assert "Pas de café ni de bar" in find_commerces.SYSTEM_PROMPT and "Pas de café ni de bar" in find_commerces.SEASON_PROMPT
    assert "Pas de café ni de bar" not in find_commerces.CAFE_PROMPT and "56.30Z" in find_commerces.REGISTER_ACTIVITIES


def test_a_shop_at_its_name_in_the_register_is_proved_without_a_page():
    register = {"actifs": [{"nom": "MADEMOISELLE TOMATES", "adresse": "580 ROUTE DE ROLEA 29217 PLOUGONVELIN",
                            "activite": "47.21Z", "actif_depuis": "2024-03-15"},
                           {"nom": "LE PAINSEUM", "adresse": "AVENUE DE LA GARE 29000 QUIMPER", "activite": "10.71C",
                            "actif_depuis": "2025-03-20"}]}
    dead = [{"url": "https://emploi.fr/x", "type_page": "agregateur", "verdict": "lien_mort"}]
    bakery = {"nom": "Le Painseum", "categorie": "boulangerie", "genre": "boulangerie", "pages": dead}
    farm = {"nom": "Mademoiselle Tomates", "categorie": "producteur", "genre": "producteur de tomates", "pages": dead}
    butcher = {"nom": "Le Painseum", "categorie": "producteur", "genre": "boucherie", "pages": dead}
    assert find_commerces.register_is_proof(bakery, register) and find_commerces.register_only_reason(bakery, register, "Quimper") is None
    assert find_commerces.register_is_proof(butcher, register)
    assert not find_commerces.register_is_proof(farm, register)
    assert find_commerces.register_only_reason(farm, register, "Plougonvelin") is None


def test_a_farm_in_the_register_still_gets_a_proof_search(monkeypatch, tmp_path):
    _chain(monkeypatch, tmp_path, _Agent(), registered="LE GALL")
    monkeypatch.setattr(find_commerces, "is_farm", lambda row: row["nom"] == "Le Gall")
    answer = find_commerces.search_commune(CITY)
    gall = next(row for row in answer["commerces"] if row["nom"] == "Le Gall")
    assert [row["nom"] for row in json.loads(next(tmp_path.iterdir()).read_text())["preuves"]] == ["Le Gall"]
    # La page trouvée cite la ferme : elle est gardée, sans relecture.
    assert gall["au_registre"] is True and not gall.get("a_relire")


def test_a_farm_without_a_page_naming_it_is_not_held_by_the_register():
    farm = {"nom": "Mademoiselle Tomates", "categorie": "producteur", "genre": "vente à la ferme",
            "pages": [{"url": "https://emploi.fr/x", "type_page": "agregateur", "verdict": "lien_mort"}]}
    assert find_commerces.is_farm(farm) and not find_commerces.has_named_page(farm)
    assert not find_commerces.is_farm({**farm, "genre": "boucherie"})


def test_a_chain_at_several_addresses_must_be_registered_at_the_place_address():
    register = {"actifs": [{"nom": "CARREFOUR EXPRESS", "adresse": "27 RUE EDOUARD CORBIERE 29200 BREST", "activite": "47.11B"},
                           {"nom": "CARREFOUR EXPRESS", "adresse": "14 RUE MARECHAL FRANCHET D'ESPEREY 29200 BREST", "activite": "47.11C"}]}
    shop = {"nom": "Carrefour Express", "categorie": "epicerie", "genre": "supérette", "pages": []}
    assert find_commerces.register_is_proof({**shop, "adresse": "27 rue Édouard Corbière, 29200 Brest"}, register)
    assert not find_commerces.register_is_proof({**shop, "adresse": "3 rue de Siam, 29200 Brest"}, register)
