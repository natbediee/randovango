from agents import analyze_commerces
from agents.analyze_commerces import apply_analysis, value_in_citation
from agents.llm_service import LLMTimeout


def test_the_market_days_must_be_in_the_sentence():
    assert value_in_citation("jours", "mardi et samedi matin", "Marché le mardi et le samedi matin, place de l'église.")
    assert not value_in_citation("jours", "jeudi matin", "Marché tous les mardis matin.")
    assert not value_in_citation("jours", "le matin", "Marché le matin.")


def test_the_season_months_must_be_in_the_sentence():
    assert value_in_citation("saison", "juin à septembre", "Ouvert de juin à septembre.")
    assert not value_in_citation("saison", "juin à septembre", "Ouvert l'été.")


def test_a_place_not_open_to_passers_by_is_marked():
    shops = [{"nom": "Le Gall"}, {"nom": "Grossiste"}]
    kept, closed, duplicates = apply_analysis(shops, {"lieux": [{"numero": 1}, {"numero": 2, "pas_un_commerce": True}]})
    assert [row["pas_un_commerce"] for row in kept] == [False, True] and closed == duplicates == []


def test_market_days_are_kept_only_for_a_market(monkeypatch):
    monkeypatch.setattr(analyze_commerces, "citation_found", lambda citation, url: True)
    page = {"url": "https://legall.fr", "type_page": "site", "verdict": "ok"}
    detail = {"champ": "jours", "valeur": "jeudi", "citation": "Ouvert le jeudi", "page": "https://legall.fr", "type_page": "site"}
    bakery = analyze_commerces.control_details({"nom": "Le Gall", "categorie": "boulangerie", "pages": [page], "details": [detail]}, "Plougonvelin")
    market = analyze_commerces.control_details({"nom": "Marché", "categorie": "marche", "pages": [page], "details": [detail]}, "Plougonvelin")
    assert bakery["jours"] is None and market["jours"] == "jeudi"


def test_a_proof_without_answer_in_time_sends_the_place_to_review(monkeypatch):
    def too_long(city, batch):
        raise LLMTimeout("délai")
    monkeypatch.setattr(analyze_commerces, "_ask_proofs", too_long)
    proofs = analyze_commerces.find_proofs({"name": "Plougonvelin"}, [{"nom": "A"}, {"nom": "B"}])
    assert proofs == [{"a_relire": analyze_commerces.PROOF_TIMED_OUT}] * 2


def test_a_duplicate_at_another_address_is_kept_but_sent_to_review():
    shops = [{"nom": "Fumaisons d'Iroise", "adresse": "Rue Winston Churchill"}, {"nom": "Fumaison d'Iroise", "adresse": "Port du Conquet"}]
    answer = {"lieux": [{"numero": 1}, {"numero": 2, "doublon_de": 1, "doublon_raison": "le stand du port de l'atelier"}]}
    kept, closed, duplicates = apply_analysis(shops, answer)
    assert [row["nom"] for row in kept] == ["Fumaisons d'Iroise", "Fumaison d'Iroise"] and duplicates == []
    assert shops[1]["doublon_possible"] == {"nom": "Fumaisons d'Iroise", "adresse": "Rue Winston Churchill",
                                            "raison": "le stand du port de l'atelier"}
