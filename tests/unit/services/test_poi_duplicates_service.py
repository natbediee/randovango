"""Les doublons de services : un même lieu chargé deux fois, quel que soit son service."""
from services import poi_duplicates_service as duplicates
from services import poi_review_service as review

# À Plougonvelin, 0,0001 degré de latitude fait environ 11 m.
METRE = 0.0001 / 11.1


def _place(id, name, address="Route de Saint-Mathieu, 29217 Plougonvelin", metres=0.0, categories=("attraction",),
           source="osm", url=None, sheet=False, restaurant=False, decided=False):
    return {"id": id, "name": name, "address": address, "latitude": 48.3349 + metres * METRE, "longitude": -4.759,
            "categories": set(categories), "source": source, "url": url, "sheet": sheet, "restaurant": restaurant,
            "decided": decided}


def _found(places):
    return [(kept["id"], other["id"], found) for _, kept, other, found, _ in duplicates.find_pairs(places)]


def test_the_same_place_drawn_twice_in_osm_is_merged_and_the_oldest_stays():
    # 2 pignons de Kéravel, poi 9690 et 9691, à 12 m l'un de l'autre.
    assert _found([_place(9691, "2 pignons de Kéravel", metres=12), _place(9690, "2 pignons de Kéravel")]) == [
        (9690, 9691, duplicates.SAME_PLACE)]


def _ty_kalon(osm_decided=False):
    return [_place(21292, "Ty Kalon", "14 Place de l'Eglise", categories=("cafe",), decided=osm_decided),
            _place(32311, "Ty Kalon", "14 place de l'Église, 29100 Le Juch", 3, ("restaurant",), "agent_restaurants",
                   sheet=True, restaurant=True)]


def test_an_agent_sheet_is_never_masked_its_twin_without_a_sheet_is():
    # Un lieu masqué est une décision humaine pour les agents : ils ne le reprendraient plus jamais.
    assert _found(_ty_kalon()) == [(32311, 21292, duplicates.SAME_PLACE)]


def test_a_twin_without_a_sheet_already_decided_by_a_human_is_a_doubt():
    assert _found(_ty_kalon(osm_decided=True)) == [(32311, 21292, duplicates.DOUBT)]


def test_shops_drawn_twice_in_osm_are_merged():
    bakeries = [_place(3203, "Boulangerie Lemaire", categories=("bakery",)),
                _place(10547, "Boulangerie Lemaire", metres=1, categories=("bakery",))]
    assert _found(bakeries) == [(3203, 10547, duplicates.SAME_PLACE)]


def test_a_restaurant_and_a_farm_at_one_address_are_left_to_a_human():
    places = [_place(32006, "Maison Legris", "20 Kastell Ac'h, 29880 Plouguerneau", categories=("restaurant",),
                     source="agent_restaurants", sheet=True, restaurant=True),
              _place(38263, "Maison Legris", "20 Kastell Ac'h, 29880 Plouguerneau", categories=("farm",),
                     source="agent_commerces", sheet=True)]
    assert [found for _, _, found in _found(places)] == [duplicates.DOUBT]


def test_a_place_a_human_has_decided_on_stays():
    places = [_place(1, "Lavoir de Benniget", categories=("lavoir",)), _place(2, "Lavoir de Benniget", metres=4, categories=("viewpoint",), decided=True)]
    assert _found(places) == []  # deux services, deux onglets
    places = [_place(1, "Lavoir de Benniget", categories=("lavoir",)), _place(2, "Lavoir de Benniget", metres=4, categories=("lavoir",), decided=True)]
    assert _found(places) == [(2, 1, duplicates.SAME_PLACE)]


def test_two_places_both_decided_by_a_human_are_only_a_doubt():
    places = [_place(1, "Akira", decided=True), _place(2, "Akira", metres=1, decided=True)]
    assert _found(places) == [(1, 2, duplicates.DOUBT)]


def test_another_street_number_is_a_doubt_never_a_merge():
    places = [_place(4651, "Café de la place", "7 place Saint-Thomas, 29570 Camaret-sur-Mer", categories=("cafe",)),
              _place(4652, "Café de la place", "2 Rue Alsace-Lorraine, 29570 Camaret-sur-Mer", 1, ("cafe",))]
    assert _found(places) == [(4651, 4652, duplicates.DOUBT)]


def test_the_same_name_further_than_25_m_is_a_doubt():
    assert _found([_place(1, "Le petit Chamarel"), _place(2, "Le petit Chamarel", metres=35)]) == [(1, 2, duplicates.DOUBT)]


def test_public_toilets_merge_only_at_the_same_spot():
    toilets = ("toilets",)
    assert _found([_place(1, "Toilettes publiques", categories=toilets),
                   _place(2, "Toilettes publiques", metres=1, categories=toilets)]) == [(1, 2, duplicates.SAME_PLACE)]
    # Deux blocs sur une même plage restent deux lieux.
    assert _found([_place(1, "Toilettes publiques", categories=toilets),
                   _place(2, "Toilettes publiques", metres=15, categories=toilets)]) == []


def test_other_services_or_names_make_no_pair():
    assert _found([_place(1, "Intermarché", categories=("fuel",)), _place(2, "Intermarché", metres=20, categories=("supermarket",))]) == []
    assert _found([_place(1, "Le Caïman"), _place(2, "Glenn Café", metres=2)]) == []
    assert _found([_place(1, "2 pignons de Kéravel"), _place(2, "2 pignons de Kéravel", metres=60)]) == []


def test_wikidata_and_osm_name_the_service_differently():
    places = [_place(33148, "Fort Montbarey", categories=("fortification",)),
              _place(18314, "fort Montbarey", categories=("museum",), source="wikidata")]
    assert _found(places) == [(33148, 18314, duplicates.SAME_PLACE)]


def test_two_restaurant_sheets_are_left_to_the_restaurant_rule():
    places = [_place(1, "Racines", sheet=True, restaurant=True, categories=("restaurant",), source="agent_restaurants"),
              _place(2, "Racines", metres=2, sheet=True, restaurant=True, categories=("restaurant",), source="agent_restaurants")]
    assert _found(places) == []


def test_a_masked_place_masks_nobody_so_a_chain_does_not_vanish():
    # A, B, C à 20 m l'un de l'autre : B est masqué au profit de A, C reste (à 40 m de A, c'est un doute).
    places = [_place(1, "Base canon"), _place(2, "Base canon", metres=20), _place(3, "Base canon", metres=40)]
    actions = {place["id"]: found for found, place, _ in duplicates.plan(duplicates.find_pairs(places))}
    assert actions == {2: duplicates.SAME_PLACE, 3: duplicates.DOUBT}


def test_a_group_keeps_a_single_place():
    # 3 « Toilettes publiques » à 1 m l'une de l'autre, rampe de Quimper.
    places = [_place(id, "Toilettes publiques", metres=metres, categories=("toilets",))
              for id, metres in ((16907, 0), (16913, 1), (16914, 2))]
    actions = duplicates.plan(duplicates.find_pairs(places))
    assert [(found, place["id"]) for found, place, _ in actions] == [(duplicates.SAME_PLACE, 16913), (duplicates.SAME_PLACE, 16914)]
    assert {detail["autre_id"] for _, _, details in actions for detail in details} == {16907}


def test_the_signal_is_reviewed_in_the_duplicates_tab():
    signal = {"id": 9, "signal_type": "doublon_service", "source": "doublons",
              "detail": {"autre_id": 9690, "autre_nom": "2 pignons de Kéravel", "autre_adresse": "Route de Saint-Mathieu",
                         "distance_m": 12, "raison": "même nom, même service"}}
    card = review.build_card("doublons", {"id": 9691, "name": "2 pignons de Kéravel"}, [signal])
    assert card["actions"][:2] == ["fusionner", "deux_lieux"] and "à 12 m" in card["preuves"][0]["texte"]
    assert review.applied_fields("fusionner", card, None) == {"masque": 1}
