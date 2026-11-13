import json

import pytest

from agents import find_commerces, find_service_links, service_chain
from agents.find_commerces import COMMERCES, in_register, registered_since
from services.service_store import same_name


def merge_answers(*answers):
    return service_chain.merge_answers(COMMERCES, *answers)


def register_for_agent(register, zone=None):
    return service_chain.register_for_agent(COMMERCES, register, zone)


def has_accepted_page(row, commune):
    return service_chain.has_accepted_page(COMMERCES, row, commune)


def _trace(tmp_path):
    """Le fichier JSON du passage : dans le dossier de la catégorie, sous le dossier des journaux."""
    return json.loads(next((tmp_path / COMMERCES.source).iterdir()).read_text())


def _found(name, url, categorie="boulangerie"):
    return {"nom": name, "genre": "boulangerie", "categorie": categorie, "adresse": None, "ancien_nom": None, "pourquoi": "",
            "lien": url, "type_lien": "agregateur", "preuve_url": url, "type_preuve": "agregateur",
            "preuve_citation": None, "preuve_date": None}


def _answer(shops=(), closed=()):
    return {"commerces": [_found(name, f"https://exemple.fr/{name}") for name in shops],
            "ecartes": [{"nom": name, "ferme": True} for name in closed]}


def test_the_shop_word_does_not_make_two_places():
    """« Boulangerie Le Gall » et « Le Gall » sont le même commerce."""
    assert same_name("Boulangerie Le Gall", "Le Gall")
    assert same_name("Marché de Plougonvelin", "Plougonvelin")


def test_two_shops_of_the_same_village_stay_two():
    """« Marché de Plougonvelin » et « L'épicerie de Plougonvelin » restent deux commerces : avant, l'un des deux était perdu."""
    merged = merge_answers(_answer(["Marché de Plougonvelin", "L'épicerie de Plougonvelin"]), _answer(["Épicerie de Plougonvelin"]))
    assert [row["nom"] for row in merged["commerces"]] == ["Marché de Plougonvelin", "L'épicerie de Plougonvelin"]
    assert len(merged["commerces"][1]["pages_vues"]) == 4


def test_a_register_line_without_the_shop_words_names_the_cafe():
    """« Bar Crêperie La Grotte » (Huelgoat) est au registre sous « LA GROTTE », débit de boissons."""
    register = {"actifs": [{"nom": "LA GROTTE", "adresse": "27 RUE DES CENDRES 29690 HUELGOAT", "activite": "56.30Z"}]}
    assert in_register({"nom": "Bar Crêperie La Grotte", "categorie": "cafe"}, register)


def test_merge_keeps_each_shop_once_with_the_pages_of_every_search():
    """Un commerce trouvé par deux recherches est gardé une fois, avec les pages des deux."""
    merged = merge_answers(_answer(["Boulangerie Le Gall"]), _answer(["Le Gall", "Ty Krampouezh"]))
    assert [row["nom"] for row in merged["commerces"]] == ["Boulangerie Le Gall", "Ty Krampouezh"]
    assert len(merged["commerces"][0]["pages_vues"]) == 4


def test_a_shop_said_closed_by_another_search_goes_to_the_analyst():
    """Un commerce retenu par une recherche et dit fermé par une autre est signalé à l'analyste."""
    merged = merge_answers(_answer(["Le Gall"]), _answer(closed=["Boulangerie Le Gall"]))
    assert merged["commerces"][0]["dit_ferme"]["nom"] == "Boulangerie Le Gall"


REGISTER = {"actifs": [{"nom": "LE GALL", "adresse": "3 RUE DE LA MER 29217 PLOUGONVELIN", "activite": "10.71C",
                        "actif_depuis": "2025-12-01"},
                       {"nom": "PLOUGONVELIN", "adresse": "PLACE DU BOURG", "activite": "47.11C", "actif_depuis": "2001-01-01"}]}


def test_the_register_shows_a_shop_by_name_or_address():
    """Le registre montre un commerce par son nom ou par son adresse."""
    assert in_register({"nom": "Boulangerie Le Gall", "categorie": "boulangerie"}, REGISTER)
    assert in_register({"nom": "Autre nom", "adresse": "3 rue de la Mer", "categorie": "boulangerie"}, REGISTER)
    assert not in_register({"nom": "Ty Krampouezh", "categorie": "epicerie"}, REGISTER)


def test_a_market_is_never_in_the_register():
    """Un marché n'est jamais prouvé ni daté par le registre."""
    market = {"nom": "Marché de Plougonvelin", "categorie": "marche"}
    assert not in_register(market, REGISTER) and registered_since(market, REGISTER) is None


def test_the_register_date_goes_by_name():
    """La date du registre se lit au nom du commerce."""
    assert registered_since({"nom": "Le Gall", "categorie": "boulangerie"}, REGISTER) == "2025-12-01"


def test_a_zone_reads_only_the_nearest_lines_of_the_register():
    """Dans une zone, l'agent ne lit que les lignes proches du repère, sans leur position."""
    register = {"actifs": [{"nom": "Près", "position": [48.30, -4.70]}, {"nom": "Loin", "position": [48.50, -4.70]},
                           {"nom": "Sans position"}]}
    zone = {"latitude": 48.30, "longitude": -4.70, "repere": "le port"}
    assert register_for_agent(register, zone) == {"actifs": [{"nom": "Près"}]}
    assert [line["nom"] for line in register_for_agent(register)["actifs"]] == ["Près", "Loin", "Sans position"]


def test_a_town_hall_page_proves_a_market_but_not_a_bakery():
    """La page de la mairie prouve un marché, pas une boulangerie."""
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
    monkeypatch.setenv("RANDOVANGO_LOG_DIR", str(tmp_path))
    monkeypatch.setattr(service_chain, "make_llm_service", lambda name: agent)
    monkeypatch.setattr(service_chain.api_registre, "load_register",
                        lambda city, codes, *zones: activities.append(codes) or {"actifs": [{"nom": registered, "activite": "10.71C"}]})
    monkeypatch.setattr(find_service_links, "read_page", lambda url: {
        "statut": 200, "final": url, "texte": "le gall marche de plougonvelin le marche a lieu le jeudi matin sur la place "
                                              + "x " * 200, "brut": ""})
    return activities


def test_the_chain_proves_a_market_by_its_town_hall_and_looks_for_the_missing_proof(monkeypatch, tmp_path):
    """La chaîne entière : le marché est prouvé par sa mairie avec ses jours, la boulangerie part chercher une preuve, le grossiste sort, et le registre est lu avec les codes des commerces."""
    activities = _chain(monkeypatch, tmp_path, _Agent())
    answer = service_chain.search_commune(COMMERCES, CITY)
    by_name = {row["nom"]: row for row in answer["commerces"]}
    assert set(by_name) == {"Le Gall", "Marché de Plougonvelin"}
    assert by_name["Marché de Plougonvelin"]["jours"] == "jeudi matin"
    assert by_name["Le Gall"]["adresse"] == "3 rue de la Mer"
    trace = _trace(tmp_path)
    assert [row["nom"] for row in trace["preuves"]] == ["Le Gall"]
    assert activities == [find_commerces.REGISTER_ACTIVITIES] and "47.11D" not in activities[0]


def test_a_shop_in_the_register_needs_no_proof_search(monkeypatch, tmp_path):
    """Un commerce au registre à son nom n'est pas envoyé à l'agent de preuve."""
    _chain(monkeypatch, tmp_path, _Agent(), registered="LE GALL")
    answer = service_chain.search_commune(COMMERCES, CITY)
    assert {row["nom"]: row["au_registre"] for row in answer["commerces"]} == {"Le Gall": True, "Marché de Plougonvelin": False}
    assert "preuves" not in _trace(tmp_path)


def test_what_was_paid_stays_readable_when_a_step_fails(monkeypatch, tmp_path):
    """Si l'analyse échoue, la trace garde les cinq recherches déjà payées et la version des consignes."""
    _chain(monkeypatch, tmp_path, _Agent(fail_on_analysis=True))
    with pytest.raises(RuntimeError):
        service_chain.search_commune(COMMERCES, CITY)
    trace = _trace(tmp_path)
    assert len(trace["recherches"]) == 5 and trace["version"] == find_commerces.COMMERCES_PROMPT_VERSION


def test_a_bar_line_proves_a_cafe_but_not_a_bakery():
    """Une ligne de débit de boissons prouve un café, pas une boulangerie, et une ligne de boulangerie ne prouve pas un café."""
    register = {"actifs": [{"nom": "LE PORT", "adresse": "1 QUAI DU PORT", "activite": "56.30Z", "actif_depuis": "2020-01-01"}]}
    assert in_register({"nom": "Le Port", "categorie": "cafe"}, register)
    assert not in_register({"nom": "Le Port", "categorie": "boulangerie"}, register)
    assert not in_register({"nom": "Le Gall", "categorie": "cafe"}, REGISTER)


def test_a_place_held_by_the_register_alone_waits_for_a_review():
    """Un commerce que seul le registre tient par son adresse attend une relecture, sauf si une page cite son nom."""
    register = {"actifs": [{"nom": "SRB (SERVICE DE REMPLACEMENT BOUCHER )", "adresse": "4 B RUE SAINT MATHIEU 29217 PLOUGONVELIN",
                            "activite": "47.22Z", "actif_depuis": "2026-02-01"}]}
    row = {"nom": "Boucherie Leonetti-Degavre", "categorie": "producteur", "adresse": "4 B rue Saint-Mathieu, 29217 Plougonvelin",
           "pages": [{"url": "https://annuaire.fr/x", "type_page": "agregateur", "verdict": "nom_absent"}]}
    reason = find_commerces.register_only_reason(row, register, "Plougonvelin")
    assert reason.startswith(find_commerces.REGISTER_ONLY) and "SRB" in reason and "2026-02-01" in reason
    named = {**row, "pages": [{"url": "https://annuaire.fr/x", "type_page": "agregateur", "verdict": "ok"}]}
    assert find_commerces.register_only_reason(named, register, "Plougonvelin") is None


def test_the_cafe_search_is_the_only_one_asked_for_cafes():
    """Seule la recherche des cafés cherche les cafés, et le registre est lu avec le code des débits de boissons."""
    assert "Pas de café ni de bar" in find_commerces.SYSTEM_PROMPT and "Pas de café ni de bar" in find_commerces.SEASON_PROMPT
    assert "Pas de café ni de bar" not in find_commerces.CAFE_PROMPT and "56.30Z" in find_commerces.REGISTER_ACTIVITIES


def test_a_shop_at_its_name_in_the_register_is_proved_without_a_page():
    """Une boutique inscrite au registre à son nom est prouvée sans page, mais pas une ferme."""
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
    """Une ferme au registre part quand même chercher une preuve, et elle est gardée si une page la cite."""
    _chain(monkeypatch, tmp_path, _Agent(), registered="LE GALL")
    monkeypatch.setattr(find_commerces, "is_farm", lambda row: row["nom"] == "Le Gall")
    answer = service_chain.search_commune(COMMERCES, CITY)
    gall = next(row for row in answer["commerces"] if row["nom"] == "Le Gall")
    assert [row["nom"] for row in _trace(tmp_path)["preuves"]] == ["Le Gall"]
    # La page trouvée cite la ferme : elle est gardée, sans relecture.
    assert gall["au_registre"] is True and not gall.get("a_relire")


def test_a_farm_without_a_page_naming_it_is_not_held_by_the_register():
    """Le genre dit si un producteur est une ferme, et une page morte ne la nomme pas."""
    farm = {"nom": "Mademoiselle Tomates", "categorie": "producteur", "genre": "vente à la ferme",
            "pages": [{"url": "https://emploi.fr/x", "type_page": "agregateur", "verdict": "lien_mort"}]}
    assert find_commerces.is_farm(farm) and not find_commerces.has_named_page(farm)
    assert not find_commerces.is_farm({**farm, "genre": "boucherie"})


def test_a_chain_at_several_addresses_must_be_registered_at_the_place_address():
    """Une enseigne inscrite à plusieurs adresses n'est prouvée qu'à l'adresse du commerce."""
    register = {"actifs": [{"nom": "CARREFOUR EXPRESS", "adresse": "27 RUE EDOUARD CORBIERE 29200 BREST", "activite": "47.11B"},
                           {"nom": "CARREFOUR EXPRESS", "adresse": "14 RUE MARECHAL FRANCHET D'ESPEREY 29200 BREST", "activite": "47.11C"}]}
    shop = {"nom": "Carrefour Express", "categorie": "epicerie", "genre": "supérette", "pages": []}
    assert find_commerces.register_is_proof({**shop, "adresse": "27 rue Édouard Corbière, 29200 Brest"}, register)
    assert not find_commerces.register_is_proof({**shop, "adresse": "3 rue de Siam, 29200 Brest"}, register)


class _RecordingAgent(_Agent):
    def __init__(self):
        super().__init__()
        self.messages = []

    def complete_json(self, system, message, schema):
        self.messages.append(message)
        return super().complete_json(system, message, schema)


def test_a_hamlet_is_searched_as_its_commune(monkeypatch, tmp_path):
    """Trézien est en Plouarzel : les agents, le contrôle des pages et la trace cherchent la commune officielle."""
    agent = _RecordingAgent()
    _chain(monkeypatch, tmp_path, agent)
    service_chain.search_commune(COMMERCES, {**CITY, "name": "Trézien", "commune": "Plouarzel"})
    assert agent.messages and all(message.startswith("COMMUNE : Plouarzel") for message in agent.messages)
    assert _trace(tmp_path)["commune"] == "Plouarzel"


def test_a_register_line_with_a_longer_name_at_the_same_address_proves_the_shop():
    """« Naima » est prouvé par NAIMA SUPERMARKET au même numéro (Brest) ; un autre nom à l'adresse, ou le même à une autre, ne prouve rien."""
    register = {"actifs": [{"nom": "NAIMA SUPERMARKET", "adresse": "12 PLACE NAPOLEON III 29200 BREST", "activite": "47.11B"},
                           {"nom": "LA BOUCHERIE DU COIN", "adresse": "1 RUE ROBESPIERRE 29200 BREST", "activite": "47.22Z"}]}
    naima = {"nom": "Naima", "categorie": "epicerie", "genre": "épicerie", "adresse": "12 place Napoléon III, 29200 Brest", "pages": []}
    assert find_commerces.register_is_proof(naima, register)
    assert not find_commerces.register_is_proof({**naima, "adresse": "3 rue de Siam, 29200 Brest"}, register)
    rouihem = {"nom": "Rouihem", "categorie": "artisan", "genre": "boucherie", "adresse": "1 rue Robespierre, 29200 Brest", "pages": []}
    assert not find_commerces.register_is_proof(rouihem, register)
    assert find_commerces.register_only_reason(naima, register, "Brest") is None


# --- Rejouer les règles d'aujourd'hui sur un fichier déjà payé ---

BREST_REGISTER = {"actifs": [{"nom": "NAIMA SUPERMARKET", "adresse": "12 PLACE NAPOLEON III 29200 BREST", "activite": "47.11B"}]}
NAIMA = {"nom": "Naima", "categorie": "epicerie", "genre": "épicerie", "adresse": "12 place Napoléon III, 29200 Brest", "pages": []}


def _replay(*rows, searched=()):
    trace = {"commune": "Brest", "version": 2, "registre": BREST_REGISTER, "final": list(rows),
             "preuves": [{"nom": name, "preuve_url": None} for name in searched]}
    answer = service_chain.replay_rules(COMMERCES, trace)
    return {row["nom"]: row.get("a_relire") for row in answer["commerces"]}, answer["preuve_a_chercher"]


def test_a_replay_takes_out_of_review_what_a_new_rule_proves():
    """Rejoué, « Naima » envoyé en relecture « registre seul » n'y part plus : NAIMA SUPERMARKET au même numéro le prouve (Brest)."""
    reviews, missing = _replay({**NAIMA, "a_relire": find_commerces.REGISTER_ONLY + " : NAIMA SUPERMARKET"})
    assert reviews == {"Naima": None} and missing == []


def test_a_replay_keeps_a_proof_that_timed_out():
    """Rejouée, une preuve restée sans réponse à temps reste à relire : aucune règle ne peut la trancher."""
    reviews, _ = _replay({**NAIMA, "nom": "Ty Bio", "adresse": None, "a_relire": service_chain.PROOF_TIMED_OUT})
    assert reviews == {"Ty Bio": service_chain.PROOF_TIMED_OUT}


def test_a_replay_sets_aside_a_place_that_would_need_a_paid_proof_search():
    """Rejoué, un commerce sans page que le registre ne prouve pas demanderait un appel payant : il est rendu à part, pas enregistré."""
    reviews, missing = _replay({**NAIMA}, {**NAIMA, "nom": "Ty Bio", "adresse": "3 rue de Siam, 29200 Brest"})
    assert list(reviews) == ["Naima"] and missing == ["Ty Bio"]


def test_a_replay_does_not_ask_again_for_a_proof_already_searched():
    """Rejoué, un commerce dont la preuve a déjà été cherchée sans succès lors du passage n'est pas mis à part : il suit les règles d'aujourd'hui."""
    reviews, missing = _replay({**NAIMA, "nom": "Ty Bio", "adresse": "3 rue de Siam, 29200 Brest"}, searched=["Ty Bio"])
    assert list(reviews) == ["Ty Bio"] and missing == []


def test_the_latest_complete_file_of_a_commune_is_replayed(monkeypatch, tmp_path):
    """Le rejeu prend, par commune, le fichier le plus récent allé au bout : un passage interrompu (sans « final ») est ignoré."""
    monkeypatch.setenv("RANDOVANGO_LOG_DIR", str(tmp_path))
    COMMERCES.trace_dir.mkdir(parents=True)
    for stamp, trace in (("20261107_200145", {"final": [{"nom": "ancien"}]}), ("20261108_101500", {"final": [{"nom": "récent"}]}),
                         ("20261109_090000", {"recherches": []})):
        (COMMERCES.trace_dir / f"Le_Conquet_{stamp}.json").write_text(json.dumps({"commune": "Le Conquet", "version": 2, **trace}))
    assert service_chain.latest_traces(COMMERCES)["Le Conquet"]["final"] == [{"nom": "récent"}]
