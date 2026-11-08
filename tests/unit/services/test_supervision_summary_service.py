"""
Le bilan compte avec les règles des pages Spots et Services : un chiffre du bilan doit être
celui que la page montre.
"""
from services import poi_review_service
from services import supervision_summary_service as summary

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
    # Une file ajoutée ou renommée dans poi_review_service doit l'être aussi dans le bilan.
    assert set(summary.SERVICE_TABS) == set(poi_review_service.TAB_SIGNALS) - set(poi_review_service.HIDDEN_TABS)
