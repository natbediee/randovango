"""
Les filtres de la page Spots (carte #186) : la ville de l'appli ou la commune d'un spot, et sa catégorie (gratuit,
payant, autres), comme au filtre de l'étape 3. Les fonctions sont pures : aucune base n'est lue.
"""
import pytest

from services.supervision import spots_review

# Deux villes de l'appli : Le Conquet et Plougonvelin, à 5 km l'une de l'autre.
CITIES = [{"id": 1, "name": "Le Conquet", "commune": "Le Conquet", "latitude": 48.36, "longitude": -4.77},
          {"id": 2, "name": "Plougonvelin", "commune": "Plougonvelin", "latitude": 48.34, "longitude": -4.72}]


def card(category="gratuit", city_id=None, town=None, code=None):
    """Une carte de la file, réduite à ce que lisent les filtres."""
    return {"categorie": category, "ville_id": city_id, "commune": town, "code_postal": code}


def test_a_spot_with_an_address_belongs_to_the_town_of_its_address():
    """Un parking dont l'adresse dit « 29217 Le Conquet » se range au Conquet, même plus près de Plougonvelin."""
    spot = {"type": "PARKING JOUR ET NUIT", "address": "Rue de la Mairie, 29217 Le Conquet",
            "latitude": 48.341, "longitude": -4.721, "postal_code": "29217"}
    assert spots_review._place_fields(spot, CITIES) == {"categorie": "gratuit", "ville_id": 1, "commune": None,
                                                         "code_postal": "29217"}


def test_a_spot_without_address_belongs_to_the_nearest_city():
    """Un spot sans adresse ni commune se range dans la ville de l'appli la plus proche."""
    spot = {"type": "CAMPING", "latitude": 48.341, "longitude": -4.721}
    fields = spots_review._place_fields(spot, CITIES)
    assert (fields["ville_id"], fields["categorie"]) == (2, "payant")


def test_a_spot_in_another_town_keeps_its_town():
    """Un spot de Guilvinec, qui n'est pas une ville de l'appli, garde sa commune pour le filtre « commune »."""
    spot = {"type": "AIRE CC STAT. GRATUIT", "address": "Port, 29730 Guilvinec", "latitude": 47.8, "longitude": -4.28}
    fields = spots_review._place_fields(spot, CITIES)
    assert (fields["ville_id"], fields["commune"]) == (None, "Guilvinec")


@pytest.mark.parametrize("city_id, town, category, expected", [
    (None, None, None, [0, 1, 2]),          # sans filtre, toute la file
    (1, None, None, [0, 1]),                # la ville n° 1
    (None, "guilvinec", None, [2]),         # une commune, sans tenir compte des majuscules
    (1, None, "payant", [1]),               # la ville et la catégorie ensemble
])
def test_the_filters_keep_the_matching_spots(city_id, town, category, expected):
    """Chaque filtre choisi retire les spots qui ne lui vont pas ; un filtre vide laisse tout passer."""
    reviews = [card("gratuit", 1), card("payant", 1), card("gratuit", None, "Guilvinec")]
    kept = spots_review.filter_reviews(reviews, city_id, town, category)
    assert kept == [reviews[i] for i in expected]


def test_the_city_search_offers_only_places_with_spots_to_review():
    """La recherche de ville propose Le Conquet (qui a un spot à relire) et Guilvinec, pas Plougonvelin, avec leurs codes."""
    reviews = [card("gratuit", 1, None, "29217"), card("gratuit", None, "Guilvinec", "29730")]
    cities, towns = spots_review.city_choices(reviews, CITIES)
    assert cities == [{"id": 1, "name": "Le Conquet", "codes": ["29217"]}]
    assert towns == [{"nom": "Guilvinec", "codes": ["29730"]}]


def test_an_unknown_category_is_refused():
    """Une catégorie qui n'est pas gratuit, payant ou autres est refusée, avant de lire la base."""
    with pytest.raises(ValueError, match="Catégorie inconnue"):
        spots_review.get_reviews(category="luxe")


def test_the_problem_filter_separates_removals_from_unverified_spots():
    """« Non vérifié » ne garde que les spots au badge « non vérifié », pas les retraits proposés par l'agent."""
    reviews = [{**card(), "probleme": "retrait"}, {**card(), "probleme": "non_verifie"}]
    assert spots_review.filter_reviews(reviews, None, None, None, "non_verifie") == [reviews[1]]


def test_an_unknown_problem_is_refused():
    """Un problème qui n'est ni un retrait proposé ni un spot non vérifié est refusé, avant de lire la base."""
    with pytest.raises(ValueError, match="Problème inconnu"):
        spots_review.get_reviews(problem="fermé")


class FakeCursor:
    """Un curseur qui rend les spots non vérifiés donnés, et garde la requête reçue."""
    def __init__(self, ids):
        self.ids, self.params = ids, None

    def execute(self, query, params=()):
        self.params = params

    def fetchall(self):
        return [{"id": spot_id} for spot_id in self.ids]


def test_an_unverified_spot_already_waiting_for_removal_is_not_counted_twice():
    """Un spot non vérifié dont l'agent propose le retrait reste dans « Retrait proposé », pas dans « Non vérifié »."""
    removal = {"id": 9, "utilisable": "non"}
    states = {2: (removal, None)}
    cursor = FakeCursor([1, 2])
    assert spots_review._unverified_ids(cursor, states) == [1]
    assert "SERVICES D'APPOINT" in cursor.params

