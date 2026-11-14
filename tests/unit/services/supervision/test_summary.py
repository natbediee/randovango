"""
Le bilan compte avec les règles des pages Spots et Services : un chiffre du bilan doit être
celui que la page montre.
"""
from services.supervision import services_review
from services.supervision import summary as summary
from utils.service_utils import POI_FRONTEND_CATEGORY_MAP

# Dernière vérification d'un spot : "non" = l'agent propose de le retirer.
REMOVE = {"id": 1, "utilisable": "non"}
KEEP = {"id": 2, "utilisable": "oui"}


def build(states=None, spot_cities=None, groups=None, pois=None, openings=0, decisions=0):
    return summary.summarize(states or {}, spot_cities or {}, groups or {}, pois or {}, openings, decisions)


def test_only_unanswered_removal_proposals_are_left_to_review() -> None:
    states = {
        10: (REMOVE, None),                                                      # proposé, à relire
        11: (REMOVE, {"decision": "garder", "verification_id": 1}),              # gardé pour cette vérification
        12: ({"id": 3, "utilisable": "non"}, {"decision": "garder", "verification_id": 1}),  # nouvelle proposition
        13: (KEEP, {"decision": "retirer", "verification_id": 2}),               # retiré par l'admin
        14: (KEEP, None),                                                        # rien à faire
    }

    spots = build(states=states, openings=4)["spots"]

    assert spots == {"a_relire": 2, "gardes": 1, "retires": 1, "ouvertures": 4}


def test_a_place_counts_once_in_each_queue_like_the_tabs() -> None:
    groups = {("liens", 7): [], ("fermetures", 7): [], ("liens", 8): []}
    pois = {7: {"service": "Restaurant"}, 8: {"service": None}}

    services = build(groups=groups, pois=pois)["services"]

    assert services["a_relire"] == 3
    assert [(file["tab"], file["n"]) for file in services["files"]] == [
        ("fermetures", 1), ("liens", 2), ("saison", 0), ("doublons", 0), ("confirmer", 0)]
    assert services["par_type"] == [{"label": "Restaurant", "n": 2}, {"label": "Type inconnu", "n": 1}]


def test_cities_add_spots_and_services_most_loaded_first() -> None:
    data = build(states={10: (REMOVE, None), 11: (REMOVE, None)},
                 spot_cities={10: "Le Conquet", 11: None},
                 groups={("liens", 7): [], ("saison", 8): []},
                 pois={7: {"commune": "Le Conquet"}, 8: {"commune": "Brest"}},
                 decisions=12)

    assert data["total"] == 4
    assert data["decisions"] == 12
    assert data["par_ville"] == [{"label": "Le Conquet", "n": 2}, {"label": "Brest", "n": 1},
                                 {"label": "Ville inconnue", "n": 1}]


def test_nothing_to_review_gives_zeros_and_every_queue() -> None:
    data = build()

    assert data["total"] == 0
    assert [file["n"] for file in data["services"]["files"]] == [0] * len(summary.SERVICE_TABS)
    assert data["par_ville"] == []


def test_the_summary_has_every_queue_of_the_services_page() -> None:
    # Une file ajoutée ou renommée dans services_review doit l'être aussi dans le bilan.
    assert set(summary.SERVICE_TABS) == set(services_review.TAB_SIGNALS) - set(services_review.HIDDEN_TABS)


def test_ratings_are_counted_by_category_then_by_pertinence_and_reason() -> None:
    """Les notes des propositions se comptent par catégorie (spots, puis onglets des services), puis par pertinence et raison."""
    rows = [
        {"objet_type": "poi", "pertinence": "fausse", "raison": "ferme_non_vu", "service_category": "restaurant"},
        {"objet_type": "poi", "pertinence": "a_corriger", "raison": "ferme_non_vu", "service_category": "restaurant"},
        {"objet_type": "poi", "pertinence": "juste", "raison": None, "service_category": "restaurant"},
        {"objet_type": "spot", "pertinence": "fausse", "raison": "preuve_faible", "service_category": None},
    ]
    counts = summary.count_ratings(rows)
    assert [(category["label"], category["n"]) for category in counts] == [("Spots", 1), ("Restauration", 3)]
    restaurants = counts[1]
    assert [(item["label"], item["n"]) for item in restaurants["pertinences"]] == [("juste", 1), ("à corriger", 1), ("fausse", 1)]
    assert restaurants["raisons"] == [{"label": "fermé non vu", "n": 2}]


def test_no_rating_gives_an_empty_count() -> None:
    """Sans aucune décision notée, le compte est vide : la page Bilan n'affiche pas le bloc."""
    assert summary.count_ratings([]) == []


def test_every_service_tab_has_a_rating_category() -> None:
    """Chaque onglet de l'étape 4 a son libellé dans le compte des notes : un nouvel onglet doit y être ajouté."""
    tabs = set(POI_FRONTEND_CATEGORY_MAP.values()) | {services_review.NO_TAB}
    assert tabs <= set(summary.RATING_CATEGORIES)


# Le filtre du Bilan (carte #186) : une ville de l'appli ou une commune.
CITIES = [{"id": 1, "name": "Le Conquet", "commune": "Le Conquet", "latitude": 48.36, "longitude": -4.77},
          {"id": 2, "name": "Plougonvelin", "commune": "Plougonvelin", "latitude": 48.34, "longitude": -4.72}]


def test_a_spot_takes_its_place_like_on_the_spots_page() -> None:
    """Un spot se range comme sur la page Spots : la ville de son adresse, sinon sa commune quand ce n'en est pas une."""
    labels = {7: {"type": "CAMPING", "address": "Rue du Port, 29217 Le Conquet", "latitude": 48.34, "longitude": -4.72},
              8: {"type": "CAMPING", "address": "Port, 29730 Guilvinec", "latitude": 47.8, "longitude": -4.28}}
    assert summary.spot_places(labels, CITIES) == {7: (1, "Le Conquet"), 8: (None, "Guilvinec")}


def test_the_city_filter_keeps_the_spots_of_the_chosen_place() -> None:
    """Choisir Le Conquet garde ses spots ; choisir Guilvinec garde les siens ; sans filtre, tout reste."""
    conquet, guilvinec = (1, "Le Conquet"), (None, "Guilvinec")
    assert summary.spot_in_place(conquet, CITIES[0], None)
    assert not summary.spot_in_place(guilvinec, CITIES[0], None)
    assert summary.spot_in_place(guilvinec, None, "guilvinec")
    assert not summary.spot_in_place(conquet, None, "Guilvinec")
    assert summary.spot_in_place(guilvinec, None, None)


def test_the_city_search_offers_places_with_spots_or_services_to_settle() -> None:
    """La recherche propose Le Conquet (un service à relire) et Guilvinec (un spot), pas Plougonvelin, sans rien à trancher."""
    places = {8: (None, "Guilvinec")}
    pois = {5: {"commune": "Le Conquet", "address": "Quai, 29217 Le Conquet"}}
    cities, towns = summary.city_search_choices(places, [8], pois, CITIES)
    assert cities == [{"id": 1, "name": "Le Conquet", "codes": ["29217"]}]
    assert towns == [{"nom": "Guilvinec", "codes": []}]


def test_the_city_summary_counts_what_the_city_has() -> None:
    """Le bilan du Conquet compte ses spots proposés par catégorie, ses spots masqués par raison, ses services par état."""
    spot_rows = [{"id": 1, "type": "PARKING JOUR ET NUIT", "verifie": 1, "nuit_interdite": 0},
                 {"id": 2, "type": "CAMPING", "verifie": 0, "nuit_interdite": 0},
                 {"id": 3, "type": "SERVICES D'APPOINT", "verifie": 1, "nuit_interdite": 0},
                 {"id": 4, "type": "CAMPING", "verifie": 1, "nuit_interdite": 1},
                 {"id": 5, "type": "CAMPING", "verifie": 0, "nuit_interdite": 0}]
    service_rows = [{"service_category": "drinking_water", "masque": 0, "statut_saison": None},
                    {"service_category": "drinking_water", "masque": 1, "statut_saison": "confirmee"}]
    place = summary.inventory(spot_rows, service_rows, "Le Conquet", hidden_ids={5})
    spots = place["spots"]
    assert (spots["total"], spots["proposes"], spots["verifies"], spots["non_verifies"], spots["masques"]) == (5, 2, 1, 1, 3)
    assert [item["n"] for item in spots["par_categorie"]] == [1, 1]
    assert [item["n"] for item in spots["masques_par_raison"]] == [1, 1, 1]
    assert {key: place["services"][key] for key in ("total", "affiches", "masques", "saisonniers")} == \
        {"total": 2, "affiches": 1, "masques": 1, "saisonniers": 1}


def test_a_service_point_is_a_spot_where_one_does_not_sleep() -> None:
    """Un point de services d'appoint, ou un spot sans type, n'est pas proposé : on n'y dort pas (comme à l'étape 3)."""
    assert summary.spot_hidden_reason({"id": 1, "type": "SERVICES D'APPOINT"}, set()) == "sans_nuit"
    assert summary.spot_hidden_reason({"id": 1, "type": None}, set()) == "sans_nuit"
    assert summary.spot_hidden_reason({"id": 1, "type": "PARKING JOUR ET NUIT"}, set()) is None


def test_a_service_outside_step_4_counts_as_masked() -> None:
    """Un lavoir, rangé hors de l'étape 4, n'est jamais montré au voyageur : il compte dans les services masqués."""
    service_rows = [{"service_category": "lavoir", "masque": 0, "statut_saison": None},
                    {"service_category": "drinking_water", "masque": 0, "statut_saison": None}]
    services = summary.inventory([], service_rows, "Le Conquet", set())["services"]
    assert (services["affiches"], services["masques"]) == (1, 1)
