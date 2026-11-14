"""Les laveries : une catégorie de plus dans la chaîne commune, sur le principe des restaurants (nom ou adresse au registre)."""
from agents import find_services, llm_config, service_chain
from agents.find_laveries import (DOUBT, LAVERIES, SYSTEM_PROMPT, accepts, doubt_review, is_generic_name, register_facts,
                                  register_is_proof)

REGISTER = {"actifs": [
    {"nom": "LAVER'YS", "adresse": "6 RUE DU PDT SALVATORE ALLENDE 29100 DOUARNENEZ", "activite": "96.01B",
     "actif_depuis": "2025-10-03"},
    {"nom": "LA BULLE DE SAVON", "adresse": "39 RUE SAINT YVES 29290 SAINT-RENAN", "activite": "96.01B",
     "actif_depuis": "2012-11-01"},
    {"nom": "SOREPRESS", "adresse": "ZA DE KERZOUAR RUE DU PONT-DE-BOIS 29290 SAINT-RENAN", "activite": "96.01B"},
    {"nom": "LAVERIE", "adresse": "2 RUE DU CENTRE 29100 DOUARNENEZ", "activite": "96.01B"},
    {"nom": "LE PORT", "adresse": "1 QUAI 29770 AUDIERNE", "activite": "56.10A"},
]}


def _laundry(name, address):
    return {"nom": name, "categorie": "laverie", "genre": "laverie automatique", "adresse": address, "pages": []}


def test_the_register_proves_a_laundry_by_its_name_even_at_the_company_address():
    """Comme un restaurant, une laverie est prouvée par son nom au registre, même quand il donne l'adresse de la société (Laver'Ys, Douarnenez)."""
    laverys = _laundry("Laver'Ys", "28 rue Pont-Neuf, 29100 Douarnenez")
    assert register_is_proof(laverys, REGISTER)
    assert register_facts(laverys, REGISTER) == {"registre_depuis": "2025-10-03", "au_registre": True}


def test_the_register_proves_a_laundry_by_its_address():
    """Une laverie inscrite sous un autre nom est prouvée par la même adresse (Saint-Renan, 39 rue Saint-Yves)."""
    assert register_is_proof(_laundry("Bulle de Savon", "39 rue Saint-Yves, 29290 Saint-Renan"), REGISTER)
    assert register_is_proof(_laundry("Lavomatique du centre", "39 rue Saint-Yves, 29290 Saint-Renan"), REGISTER)


def test_a_generic_name_is_proved_only_by_its_address():
    """48 laveries d'OSM s'appellent « Laverie » : ce nom seul ne prouve rien, seule la même adresse le fait."""
    assert is_generic_name("Laverie automatique") and not is_generic_name("Laverie du Port")
    assert not register_is_proof(_laundry("Laverie", "Place de la Liberté, 29770 Audierne"), REGISTER)
    assert register_is_proof(_laundry("Laverie", "2 rue du Centre, 29100 Douarnenez"), REGISTER)


def test_a_cabin_of_a_national_brand_is_not_in_the_register():
    """Une cabine Wash Me n'est pas au registre de sa commune (Lannilis) : sa preuve sera cherchée sur une page."""
    assert not register_is_proof(_laundry("Wash Me", "Rue Auguste Favé, 29870 Lannilis"), REGISTER)


def test_another_activity_of_the_register_proves_nothing():
    """Une ligne d'un autre code (un restaurant au même nom) ne prouve pas une laverie."""
    assert not register_is_proof(_laundry("Le Port", "Quai, 29770 Audierne"), REGISTER)


def test_the_laundries_are_one_more_category_of_the_chain():
    """Les laveries passent dans la chaîne commune : une recherche (deux n'apportaient rien à Douarnenez), le code 96.01B, les annonces « laverie » du BODACC, leurs trois agents déclarés."""
    assert LAVERIES in find_services.CATEGORIES
    assert len(LAVERIES.searches) == 1 and LAVERIES.register_activities == ("96.01B",)
    assert LAVERIES.notice_words == ("laverie",)
    assert {LAVERIES.find_agent, LAVERIES.analyze_agent, LAVERIES.prove_agent} <= set(llm_config.AGENTS)
    assert "pas_une_laverie" in str(service_chain.analysis_schema(LAVERIES))


def test_the_sheet_goes_to_the_shops_table_and_the_service_to_the_laundry_tab():
    """La fiche d'une laverie va dans la table des commerces, et le service créé rejoint l'onglet « Laverie »."""
    assert LAVERIES.sheet_table == "commerces" and LAVERIES.categories == ["laverie"]
    assert LAVERIES.new_service(_laundry("Laverie du Port", None)) == "laundry"


def test_a_big_city_is_searched_by_zones():
    """Une recherche rend 15 lieux au plus : au-delà de 15 lignes au registre, les laveries d'une ville sont cherchées par zones (Marseille, Brest)."""
    lines = [{"nom": f"Laverie {number}"} for number in range(16)]
    assert service_chain.is_big_city(LAVERIES, {"actifs": lines}) and not service_chain.is_big_city(LAVERIES, {"actifs": lines[:15]})


def test_a_wash_me_cabin_is_shown_as_revolution_laundry():
    """Une cabine Wash.me s'appelle Revolution Laundry, le nom que connaît Google Maps, avec Wash.me comme autre nom pour retrouver celle d'OSM (pilote de Douarnenez, 14 novembre 2026)."""
    assert '"Revolution Laundry", avec "Wash.me" dans "ancien_nom"' in SYSTEM_PROMPT


CABIN = "https://stores.revolution-laundry.com/fr-fr/france-fra/douarnenez/laverie-revolution-laundry-19597108"


def _page(url, status=200, verdict="nom_absent", type_page="site", final=None):
    """Une page contrôlée par le code, comme service_chain la garde : son adresse, et celle où elle a abouti."""
    return {"url": url, "final": final or url, "statut": status, "verdict": verdict, "type_page": type_page}


def test_the_page_of_a_cabin_on_the_merchant_site_proves_it():
    """La page d'une cabine sur le site de Revolution Laundry prouve la cabine, même si le code n'y lit rien (contenu par JavaScript) : c'est le marchand qui la publie (Douarnenez, 14 novembre 2026)."""
    assert accepts(_page(CABIN), {"nom": "Revolution Laundry"}, "Douarnenez")


def test_a_cabin_page_of_another_commune_or_a_dead_one_proves_nothing():
    """La page d'une cabine d'une autre commune, ou une page qui n'existe plus, ne prouve rien."""
    assert not accepts(_page(CABIN), {"nom": "Revolution Laundry"}, "Crozon")
    assert not accepts(_page(CABIN, status=404, verdict="lien_mort"), {"nom": "Revolution Laundry"}, "Douarnenez")


def test_a_cabin_page_sent_back_to_the_home_page_proves_nothing():
    """Une page de cabine disparue ou inventée renvoie vers l'accueil du site : elle ne prouve rien (adresses de 2023 du plan du site)."""
    gone = _page(CABIN, final="https://stores.revolution-laundry.com/fr-fr")
    assert not accepts(gone, {"nom": "Revolution Laundry"}, "Douarnenez")


def test_the_page_of_the_commune_does_not_prove_a_cabin():
    """La page qui liste les cabines de la commune ne désigne aucune cabine en particulier."""
    commune_page = "https://stores.revolution-laundry.com/fr-fr/france-fra/douarnenez"
    assert not accepts(_page(commune_page), {"nom": "Revolution Laundry"}, "Douarnenez")


def test_a_directory_still_proves_nothing():
    """Un annuaire de laveries (citywash.fr) ne suffit toujours pas, comme pour les autres services."""
    directory = _page("https://www.citywash.fr/laveries-automatiques/29046-douarnenez/x.htm", verdict="ok", type_page="agregateur")
    assert not accepts(directory, {"nom": "Revolution Laundry"}, "Douarnenez")


def test_the_search_asks_for_each_cabin_with_its_own_page():
    """La recherche demande chaque cabine de la commune, avec la page de cette cabine sur le site du marchand."""
    assert "retiens\nchacune comme un lieu" in SYSTEM_PROMPT and "stores.revolution-laundry.com" in SYSTEM_PROMPT


def test_a_laundry_found_with_a_directory_only_goes_to_human_review():
    """Une laverie trouvée sur un annuaire seulement n'est plus écartée : elle attend une relecture humaine (Ma Nouvelle Laverie, Douarnenez, 14 novembre 2026)."""
    directory = _page("https://www.villepratique.fr/laveries-automatiques/douarnenez-29100", verdict="ok", type_page="agregateur")
    row = {"nom": "Ma Nouvelle Laverie", "pages": [directory], "au_registre": False}
    assert doubt_review(row, None, "Douarnenez") == DOUBT
    assert LAVERIES.review_after_proof is doubt_review


def test_a_proved_laundry_needs_no_review():
    """Une laverie prouvée par le registre ou par la page de sa cabine n'attend aucune relecture."""
    assert doubt_review({"nom": "Laver'Ys", "pages": [], "au_registre": True}, None, "Douarnenez") is None
    assert doubt_review({"nom": "Revolution Laundry", "pages": [_page(CABIN)], "au_registre": False}, None, "Douarnenez") is None


def test_the_laundries_already_known_are_given_as_a_hint():
    """L'agent reçoit les laveries déjà en base comme indice : OSM plaçait les cabines de Douarnenez sans leur nom."""
    assert LAVERIES.hint_services == ("laundry",)
    assert '"en_base"' in SYSTEM_PROMPT


def test_a_receivership_does_not_close_a_laundry():
    """Un redressement judiciaire ne ferme pas une laverie : la recherche le dit (Ma Buanderie, écartée à tort le 14 novembre 2026)."""
    assert "redressement judiciaire) ou une radiation" in SYSTEM_PROMPT


def test_several_cabins_of_one_name_stay_several_laundries():
    """Une commune a souvent plusieurs cabines Revolution Laundry : à nom égal, deux rues font deux laveries."""
    assert LAVERIES.several_per_name
