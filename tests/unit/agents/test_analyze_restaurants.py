import pytest

from agents import llm_config, service_chain
from agents.find_restaurants import RESTAURANTS
from agents.llm_service import LLMTimeout, LLMUnavailable
from agents.service_chain import value_in_citation


def apply_analysis(rows, answer):
    return service_chain.apply_analysis(RESTAURANTS, rows, answer)


def control_details(row, commune):
    return service_chain.control_details(RESTAURANTS, row, commune)


def analyze_commune(city, rows, register=None):
    return service_chain.analyze_commune(RESTAURANTS, city, rows, register)


def find_proofs(city, rows):
    return service_chain.find_proofs(RESTAURANTS, city, rows)


def _answer(*places):
    return {"lieux": [{"numero": number, "ferme": False, "ferme_page": None, "ferme_citation": None,
                       "doublon_de": None, "doublon_raison": None, "details": [], **place}
                      for number, place in places]}


def test_details_go_to_the_right_place():
    kept, closed, _ = apply_analysis([{"nom": "A"}, {"nom": "B"}], _answer((2, {"details": [{"champ": "budget"}]})))
    assert [(row["nom"], row["details"]) for row in kept] == [("A", []), ("B", [{"champ": "budget"}])]
    assert closed == []


def test_a_proved_closure_removes_the_place(monkeypatch):
    monkeypatch.setattr(service_chain, "citation_found", lambda citation, url: True)
    kept, closed, _ = apply_analysis([{"nom": "A"}], _answer((1, {"ferme": True, "ferme_citation": "A a fermé", "ferme_page": "https://x.fr"})))
    assert kept == [] and closed == ["A"]


def test_a_closure_on_an_unreadable_page_removes_the_place(monkeypatch):
    monkeypatch.setattr(service_chain, "citation_found", lambda citation, url: None)
    kept, closed, _ = apply_analysis([{"nom": "A"}], _answer((1, {"ferme": True, "ferme_citation": "A a fermé", "ferme_page": "https://x.fr"})))
    assert kept == [] and closed == ["A"]


def test_a_closure_without_a_page_does_not_remove_the_place():
    kept, closed, _ = apply_analysis([{"nom": "A"}], _answer((1, {"ferme": True, "ferme_citation": "Registre : fermé"})))
    assert [row["nom"] for row in kept] == ["A"] and closed == []


def test_a_registry_alert_stays_on_the_place():
    kept, _, _ = apply_analysis([{"nom": "A"}], _answer((1, {"alerte_registre": "liquidation judiciaire"})))
    assert kept[0]["alerte_registre"] == "liquidation judiciaire"


class _Service:
    last_run = {}

    def __init__(self, answer):
        self.answer, self.messages = answer, []

    def complete_json(self, system, message, schema):
        self.messages.append(message)
        return self.answer(message) if callable(self.answer) else self.answer


def _found(name):
    return {"nom": name, "adresse": None, "lien": "https://a.fr", "preuve_url": "https://a.fr"}


def test_a_place_without_a_table_is_removed(monkeypatch):
    service = _Service(_answer((1, {"pas_un_restaurant": True}), (2, {})))
    monkeypatch.setattr(service_chain, "make_llm_service", lambda name: service)
    kept = analyze_commune({"name": "X"}, [_found("La Vinotière"), _found("La Ria")])
    assert [row["nom"] for row in kept] == ["La Ria"]


def test_the_register_reaches_the_analyst_and_the_address_comes_back(monkeypatch):
    service = _Service(_answer((1, {"adresse": "1 quai"})))
    monkeypatch.setattr(service_chain, "make_llm_service", lambda name: service)
    kept = analyze_commune({"name": "X"}, [_found("A")], {"actifs": [{"nom": "CAFE KONK"}]})
    assert "CAFE KONK" in service.messages[0] and kept[0]["adresse"] == "1 quai"


def test_proofs_go_by_small_batches_and_keep_the_order(monkeypatch):
    def answer(message):
        count = message.count('"numero"')
        return {"lieux": [{"numero": number, "preuve_url": f"https://x.fr/{number}"} for number in range(1, count + 1)]}

    service = _Service(answer)
    monkeypatch.setattr(service_chain, "make_llm_service", lambda name: service)
    rows = [{"nom": f"Lieu {number}"} for number in range(7)]
    proofs = find_proofs({"name": "X"}, rows)
    assert len(service.messages) == 2
    assert [proof["preuve_url"] for proof in proofs] == [f"https://x.fr/{n}" for n in (1, 2, 3, 4, 5, 1, 2)]


def test_no_proof_to_find_makes_no_call(monkeypatch):
    monkeypatch.setattr(service_chain, "make_llm_service", lambda name: 1 / 0)
    assert find_proofs({"name": "X"}, []) == []


def test_a_closure_absent_from_the_page_is_ignored(monkeypatch):
    monkeypatch.setattr(service_chain, "citation_found", lambda citation, url: False)
    kept, closed, _ = apply_analysis([{"nom": "A"}], _answer((1, {"ferme": True, "ferme_citation": "A a fermé", "ferme_page": "https://x.fr"})))
    assert [row["nom"] for row in kept] == ["A"] and closed == []


def test_a_duplicate_gives_way_at_the_same_address():
    rows = [{"nom": "Crêperie Laer-Mor", "adresse": "3 rue Poncelin, 29217 Le Conquet"},
            {"nom": "Crêperie Les Boucaniers", "adresse": "3 Rue Poncelin, 29217 Le Conquet"}]
    kept, _, duplicates = apply_analysis(rows, _answer((1, {"doublon_de": 2})))
    assert [row["nom"] for row in kept] == ["Crêperie Les Boucaniers"] and duplicates == ["Crêperie Laer-Mor"]


def test_two_tables_sharing_an_address_stay():
    rows = [{"nom": "Hostellerie", "adresse": "7 place Saint-Tanguy"}, {"nom": "Bistrot 1954", "adresse": "7 place Saint-Tanguy"}]
    assert len(apply_analysis(rows, _answer())[0]) == 2


def test_a_duplicate_at_another_address_is_refused():
    rows = [{"nom": "A", "adresse": "1 quai"}, {"nom": "B", "adresse": "2 quai"}]
    kept, _, duplicates = apply_analysis(rows, _answer((1, {"doublon_de": 2})))
    assert len(kept) == 2 and duplicates == []


def test_a_duplicate_without_address_is_refused():
    rows = [{"nom": "A", "adresse": None}, {"nom": "B", "adresse": None}]
    assert len(apply_analysis(rows, _answer((1, {"doublon_de": 2})))[0]) == 2


def test_an_impossible_duplicate_number_is_refused():
    rows = [{"nom": "A", "adresse": "1 quai"}]
    assert len(apply_analysis(rows, _answer((1, {"doublon_de": 1})))[0]) == 1
    assert len(apply_analysis(rows, _answer((1, {"doublon_de": 9})))[0]) == 1


def test_two_places_pointing_at_each_other_both_stay():
    rows = [{"nom": "A", "adresse": "1 quai"}, {"nom": "B", "adresse": "1 quai"}]
    assert len(apply_analysis(rows, _answer((1, {"doublon_de": 2}), (2, {"doublon_de": 1})))[0]) == 2


def test_a_disputed_closure_reaches_the_analyst(monkeypatch):
    sent = {}

    class Service:
        last_run = {}

        def complete_json(self, system, message, schema):
            sent["message"] = message
            return _answer()

    monkeypatch.setattr(service_chain, "make_llm_service", lambda name: Service())
    row = {"nom": "A", "adresse": "1 quai", "lien": "https://a.fr", "preuve_url": "https://a.fr",
           "dit_ferme": {"nom": "A", "raison": "société liquidée", "ferme": True, "page": "https://annuaire.fr"}}
    assert [place["nom"] for place in analyze_commune({"name": "X"}, [row])] == ["A"]
    assert "société liquidée" in sent["message"] and "https://annuaire.fr" in sent["message"]


def test_the_citation_must_hold_the_value():
    assert value_in_citation("saison", "avril à septembre", "Ouvert d'avril à septembre")
    assert not value_in_citation("saison", "mars à novembre", "Ouvert de mars à octobre")
    assert value_in_citation("saison", None, "Ouvert seulement l'été")
    assert value_in_citation("distinction", "1 étoile Michelin", "UNE ETOILE AU GUIDE MICHELIN")
    assert value_in_citation("distinction", "1 étoile Michelin", "Une étoile au guide Michelin")
    assert not value_in_citation("distinction", "1 étoile Michelin", "Cité par le guide Michelin")
    assert value_in_citation("distinction", "Bib Gourmand", "Le restaurant a reçu un Bib Gourmand")
    assert value_in_citation("distinction", "Assiette Michelin", "Une assiette au guide Michelin")
    assert value_in_citation("distinction", "Gault & Millau 15,5/20", "Noté 15,5/20 au Gault & Millau")


def _row(*details):
    return {"nom": "Keringar", "adresse": None, "ancien_nom": None, "details": list(details),
            "pages": [{"url": "https://keringar.fr", "type_page": "site", "verdict": "ok"}]}


def _detail(field, value, citation, page="https://keringar.fr"):
    return {"champ": field, "valeur": value, "citation": citation, "page": page, "type_page": "site"}


def test_a_detail_whose_citation_is_absent_from_the_page_is_dropped(monkeypatch):
    monkeypatch.setattr(service_chain, "citation_found", lambda citation, url: False)
    checked = control_details(_row(_detail("saison", "mars à novembre", "Ouvert de mars à novembre")), "Le Conquet")
    assert "budget" not in checked and "jours_fermeture" not in checked
    assert not checked["saisonnier"] and checked["mois_ouverture"] is None and len(checked["pages"]) == 1


def test_an_unreadable_page_proves_nothing(monkeypatch):
    monkeypatch.setattr(service_chain, "citation_found", lambda citation, url: None)
    assert control_details(_row(_detail("distinction", "Bib Gourmand", "Un Bib Gourmand")), "Le Conquet")["distinction"] is None


def test_a_found_detail_is_kept_with_its_proof(monkeypatch):
    monkeypatch.setattr(service_chain, "citation_found", lambda citation, url: True)
    star = _detail("distinction", "Étoile Michelin", "Une étoile au guide Michelin")
    checked = control_details(_row(star, _detail("distinction", "Bib Gourmand", "Un Bib Gourmand")), "Le Conquet")
    assert checked["distinction"] == "Étoile Michelin"
    assert [(page.get("porte_sur"), page.get("citation")) for page in checked["pages"]] == [(None, None), ("distinction", "Une étoile au guide Michelin")]


def test_a_detail_on_a_refused_page_is_dropped(monkeypatch):
    monkeypatch.setattr(service_chain, "citation_found", lambda citation, url: True)
    monkeypatch.setattr(service_chain, "check_links_of", lambda row, place: [{"url": "https://autre.fr", "type_page": "site", "verdict": "nom_absent"}])
    assert control_details(_row(_detail("distinction", "Bib Gourmand", "Un Bib Gourmand", "https://autre.fr")), "Le Conquet")["distinction"] is None


def test_the_analyst_reads_every_page_found_except_the_excluded_sites():
    row = {"pages": [{"url": "https://guide.michelin.com/x"}, {"url": "https://iroise-bretagne.bzh/x"}, {"url": "https://iroise-bretagne.bzh/x"}]}
    assert service_chain.pages_to_read(row) == ["https://iroise-bretagne.bzh/x"]


def test_a_batch_too_long_is_asked_again_place_by_place(monkeypatch):
    def answer(message):
        if message.count('"numero"') > 1:
            raise LLMTimeout("trop long")
        if "Le Galion" in message:
            raise LLMTimeout("trop long")
        return {"lieux": [{"numero": 1, "preuve_url": "https://x.fr"}]}

    service = _Service(answer)
    monkeypatch.setattr(service_chain, "make_llm_service", lambda name: service)
    rows = [{"nom": name} for name in ("Le Kraken", "Le Galion", "Le Caïman")]
    proofs = find_proofs({"name": "Ploudalmézeau"}, rows)
    assert len(service.messages) == 4
    assert proofs[0]["preuve_url"] == proofs[2]["preuve_url"] == "https://x.fr"
    assert proofs[1] == {"a_relire": service_chain.PROOF_TIMED_OUT}


def test_a_quota_limit_is_not_taken_for_a_batch_too_long(monkeypatch):
    def answer(message):
        raise LLMUnavailable("You've hit your session limit")

    service = _Service(answer)
    monkeypatch.setattr(service_chain, "make_llm_service", lambda name: service)
    with pytest.raises(LLMUnavailable):
        find_proofs({"name": "X"}, [{"nom": "A"}, {"nom": "B"}])
    assert len(service.messages) == 1


def test_proofs_have_their_own_shorter_delay(monkeypatch):
    names = []
    monkeypatch.setattr(service_chain, "make_llm_service", lambda name: names.append(name) or _Service({"lieux": []}))
    find_proofs({"name": "X"}, [{"nom": "A"}])
    assert names == ["prove_restaurants"]
    assert llm_config.AGENTS["prove_restaurants"].timeout < llm_config.AGENTS["analyze_restaurants"].timeout
