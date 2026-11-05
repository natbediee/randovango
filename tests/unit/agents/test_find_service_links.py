from agents.find_service_links import (apply_social_rule, best_link, build_user_message, commune_of, control_page,
                                       is_aggregator, is_dedicated_page, name_on_page, result_signals, social_key)
from services.pepite_service import name_key

PLACE = {"name": "Kaïts Pita Bar", "commune": "Marseille", "cp": "13008", "telephone": "+33 4 91 25 32 82"}
LONG = " texte " * 100


def page(text, statut=200, final="https://exemple.fr/"):
    key = name_key(text)
    return {"statut": statut, "final": final, "texte": key, "brut": key}


def link(type_page="site"):
    return {"url": "https://exemple.fr/", "type_page": type_page}


def test_commune_of_reads_the_address() -> None:
    assert commune_of("66 Avenue de la Mer, 29250 Saint-Pol-de-Léon") == ("Saint-Pol-de-Léon", "29250")
    assert commune_of("Rue sans code") == (None, None)


def test_name_on_page_rejects_a_homonym_of_a_generic_name() -> None:
    assert name_on_page("Restaurant Le Goyen", "bienvenue au le goyen a audierne")
    assert name_on_page("Café du Port", "le cafe du port a roscoff")
    assert not name_on_page("Café du Port", "un cafe et le port de roscoff")


def test_control_accepts_name_and_commune() -> None:
    place = {**PLACE, "name": "Busan"}
    assert control_page(link(), page(f"Busan restaurant coréen Marseille {LONG}"), place)["verdict"] == "ok"


def test_control_accepts_the_phone_when_the_name_differs() -> None:
    """Kaïts Pita Bar s'appelle Kaïts Kitchen sur son site, mais le téléphone y est."""
    verdict = control_page(link(), page(f"Kaits Kitchen Marseille 04 91 25 32 82 {LONG}"), PLACE)["verdict"]
    assert verdict == "ok_telephone"


def test_control_sends_another_name_to_review() -> None:
    """Le Protis : le nom donné par l'agent n'est pas une preuve, il faut qu'un humain confirme."""
    place = {"name": "Brasserie Le Portis", "commune": "Marseille", "cp": "13002"}
    text = page(f"Le Protis Marseille {LONG}")
    assert control_page(link(), text, place)["verdict"] == "nom_absent"
    assert control_page(link(), text, place, "Le Protis")["verdict"] == "a_valider_nom"


def test_control_refuses_a_page_of_another_commune() -> None:
    place = {"name": "La Cabane", "commune": "Plougonvelin", "cp": "29217"}
    assert control_page(link(), page(f"La Cabane à Quimper {LONG}"), place)["verdict"] == "commune_absente"


def test_control_reports_dead_and_unreadable_pages() -> None:
    place = {**PLACE, "name": "Busan"}
    assert control_page(link(), page("", statut=404), place)["verdict"] == "lien_mort"
    assert control_page(link(), page("", statut=403), place)["verdict"] == "page_illisible"
    assert control_page(link(), page("Busan Marseille"), {**place, "name": "Autre"})["verdict"] == "page_illisible"


def test_a_list_page_is_not_the_page_of_a_place() -> None:
    """La page « où manger » de la mairie de Huelgoat cite L'Hermine, sans lui être consacrée."""
    place = {"name": "L'Hermine", "commune": "Huelgoat", "cp": "29690"}
    text = "ou manger place alphonse penven " + "autre adresse " * 40 + "l hermine a huelgoat"
    list_page = {"statut": 200, "final": "https://mairie-huelgoat.fr/ou-manger", "texte": text, "brut": text}

    assert control_page(link("office_tourisme"), list_page, place)["verdict"] == "page_de_liste"
    assert is_dedicated_page("Le Café", "https://x.fr", "autre")   # un nom générique ne permet pas de conclure


def test_aggregators_are_recognized() -> None:
    assert is_aggregator("https://www.sluurpy.fr/brest/restaurant/1/x")
    assert not is_aggregator("https://www.le-roof.com/fr/")


def test_social_key_reads_slug_or_id() -> None:
    assert social_key("https://www.facebook.com/profile.php?id=100030320897258") == "100030320897258"
    assert social_key("https://www.facebook.com/DiwaliBrest/") == "diwalibrest"


def test_social_link_needs_an_accepted_page_that_cites_it() -> None:
    cited = {"url": "https://www.facebook.com/DiwaliBrest/", "type_page": "facebook", "verdict": "page_illisible"}
    other = {"url": "https://www.facebook.com/Autre/", "type_page": "facebook", "verdict": "page_illisible"}

    result = apply_social_rule([cited, other], "suivez nous facebook com diwalibrest")

    assert [item["verdict"] for item in result] == ["ok_rebond", "a_valider_social"]


def test_best_link_prefers_accepted_then_the_site() -> None:
    tourism = {"url": "t", "type_page": "office_tourisme", "verdict": "ok"}
    site = {"url": "s", "type_page": "site", "verdict": "ok"}
    review = {"url": "r", "type_page": "site", "verdict": "a_valider_nom"}
    refused = {"url": "x", "type_page": "site", "verdict": "nom_absent"}

    assert best_link([tourism, site, review, refused]) is site
    assert best_link([review, tourism]) is tourism
    assert best_link([refused]) is None


def test_result_signals_keep_the_proof() -> None:
    row = {"fermeture": "reprise", "citation": None, "page_fermeture": None, "autre_nom": "La Petite Folie",
           "saison": "probable", "saison_citation": "paillote", "saison_page": None, "mois_ouverture": None}
    links = [{"url": "s", "type_page": "site", "verdict": "ok"}]

    signals = dict(result_signals(row, links))

    assert signals["lien_agent"]["niveau"] == "auto"
    assert signals["fermeture_agent"]["autre_nom"] == "La Petite Folie"
    assert signals["saison_agent"]["statut"] == "probable"


def test_months_without_a_found_quote_stay_probable() -> None:
    row = {"fermeture": "aucune", "saison": "confirmee", "saison_citation": "ouvert en été", "saison_page": None,
           "mois_ouverture": "juillet"}

    assert dict(result_signals(row, []))["saison_agent"]["statut"] == "probable"


def test_build_user_message_gives_the_phone_when_known() -> None:
    message = build_user_message([{"id": 1, "name": "A", "service": "Café", "address": "1 rue X", "telephone": "02"},
                                  {"id": 2, "name": "B", "service": "Café", "address": "2 rue X", "telephone": None}])
    assert "[1] A (Café), 1 rue X, tél. 02" in message
    assert "[2] B (Café), 2 rue X" in message
    assert message.count("tél.") == 1
