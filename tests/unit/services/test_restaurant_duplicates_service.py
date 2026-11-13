from services import poi_review_service as review
from services import restaurant_duplicates_service as duplicates


def _place(id, name, address, latitude=47.6500, longitude=-2.7600):
    return {"id": id, "name": name, "address": address, "latitude": latitude, "longitude": longitude}


def test_the_rule_merges_the_same_table_under_two_names():
    pairs = duplicates.find_pairs([_place(1, "Racines", "82 Boulevard de la France Libre, 29160 Crozon"),
                                   _place(2, "Restaurant Racines", "82 boulevard de la France Libre, 29160 Crozon")])
    assert [(older["id"], newer["id"], found) for _, older, newer, found, _ in pairs] == [(1, 2, duplicates.SAME_PLACE)]


def test_two_tables_at_one_address_are_a_doubt_never_a_merge():
    pairs = duplicates.find_pairs([_place(1, "Le Grill de la Côte", "2460 Route du Conquet, 29280 Locmaria-Plouzané"),
                                   _place(2, "La Java", "2460 Route du Conquet, 29280 Locmaria-Plouzané")])
    assert [found for _, _, _, found, _ in pairs] == [duplicates.DOUBT]


def test_neighbours_make_no_pair():
    assert duplicates.find_pairs([_place(1, "Le Caïman", "44 rue du Port, 29830 Ploudalmézeau"),
                                  _place(2, "Glenn Café", "34 rue du Port, 29830 Ploudalmézeau", 47.6501)]) == []


def test_places_too_far_apart_make_no_pair():
    assert duplicates.find_pairs([_place(1, "Racines", "82 bd de la France Libre, 29160 Crozon"),
                                  _place(2, "Restaurant Racines", "82 bd de la France Libre, 29160 Crozon", 47.6600)]) == []


def test_a_merge_masks_the_place_and_is_shown_in_its_own_review_tab():
    """« Restaurant Racines », doublon possible de « Racines », se relit dans « Doublons » : garder l'un ou l'autre, « Deux lieux » ou « Aucun des deux »."""
    signal = {"signal_type": "doublon_restaurant", "source": "doublons",
              "detail": {"autre_id": 1, "autre_nom": "Racines", "autre_adresse": "82 bd", "distance_m": 0, "raison": "même adresse, autre nom"}}
    card = review.build_card("doublons", {"id": 2, "name": "Restaurant Racines"}, [{**signal, "id": 9}])
    assert card["actions"] == ["garder_celui_ci", "fusionner", "deux_lieux", "retirer_les_deux", "retirer", "autre_nom", "autre_lien", "autre_maps"] and "Racines" in card["preuves"][0]["texte"]
    assert review.applied_fields("fusionner", card, None) == {"masque": 1}
    assert review.applied_fields("deux_lieux", card, None) == {}
