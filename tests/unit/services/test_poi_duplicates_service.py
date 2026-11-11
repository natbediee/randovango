"""Les doublons de services : un même lieu chargé deux fois, quel que soit son service."""
from services import poi_duplicates_service as duplicates
from services import poi_review_service as review

# À Plougonvelin, 0,0001 degré de latitude fait environ 11 m.
METRE = 0.0001 / 11.1


def _place(id, name, address="Route de Saint-Mathieu, 29217 Plougonvelin", metres=0.0, categories=("attraction",),
           source="osm", url=None, sheet=False, restaurant=False, decided=False, shop=None):
    return {"id": id, "name": name, "address": address, "latitude": 48.3349 + metres * METRE, "longitude": -4.759,
            "categories": set(categories), "source": source, "url": url, "sheet": sheet or bool(shop), "restaurant": restaurant,
            "decided": decided, "shop": shop}


def _found(places):
    return [(kept["id"], other["id"], found) for _, kept, other, found, _ in duplicates.find_pairs(places)]


def test_the_same_place_drawn_twice_in_osm_is_merged_and_the_oldest_stays():
    """Un lieu dessiné deux fois dans OSM est fusionné, le plus ancien reste (2 pignons de Kéravel, 9690 et 9691, à 12 m)."""
    assert _found([_place(9691, "2 pignons de Kéravel", metres=12), _place(9690, "2 pignons de Kéravel")]) == [
        (9690, 9691, duplicates.SAME_PLACE)]


def _ty_kalon(osm_decided=False):
    return [_place(21292, "Ty Kalon", "14 Place de l'Eglise", categories=("cafe",), decided=osm_decided),
            _place(32311, "Ty Kalon", "14 place de l'Église, 29100 Le Juch", 3, ("restaurant",), "agent_restaurants",
                   sheet=True, restaurant=True)]


def test_an_agent_sheet_is_never_masked_its_twin_without_a_sheet_is():
    """Le service qui a la fiche d'un agent reste, son jumeau d'OSM sans fiche est masqué (Ty Kalon, au Juch)."""
    assert _found(_ty_kalon()) == [(32311, 21292, duplicates.SAME_PLACE)]


def test_a_twin_without_a_sheet_already_decided_by_a_human_is_a_doubt():
    """Si un humain a déjà tranché le jumeau sans fiche, la règle ne le masque pas : c'est un doute."""
    assert _found(_ty_kalon(osm_decided=True)) == [(32311, 21292, duplicates.DOUBT)]


def test_shops_drawn_twice_in_osm_are_merged():
    """Un commerce dessiné deux fois dans OSM, à 1 m, est fusionné (Boulangerie Lemaire)."""
    bakeries = [_place(3203, "Boulangerie Lemaire", categories=("bakery",)),
                _place(10547, "Boulangerie Lemaire", metres=1, categories=("bakery",))]
    assert _found(bakeries) == [(3203, 10547, duplicates.SAME_PLACE)]


def test_a_restaurant_and_a_farm_at_one_address_are_left_to_a_human():
    """Un restaurant et une ferme du même nom, chacun avec sa fiche d'agent, restent un doute pour un humain (Maison Legris)."""
    places = [_place(32006, "Maison Legris", "20 Kastell Ac'h, 29880 Plouguerneau", categories=("restaurant",),
                     source="agent_restaurants", sheet=True, restaurant=True),
              _place(38263, "Maison Legris", "20 Kastell Ac'h, 29880 Plouguerneau", categories=("farm",),
                     source="agent_commerces", sheet=True)]
    assert [found for _, _, found in _found(places)] == [duplicates.DOUBT]


def test_a_place_a_human_has_decided_on_stays():
    """Entre deux jumeaux, celui qu'un humain a déjà tranché reste ; deux services d'onglets différents ne font pas une paire."""
    places = [_place(1, "Lavoir de Benniget", categories=("lavoir",)), _place(2, "Lavoir de Benniget", metres=4, categories=("viewpoint",), decided=True)]
    assert _found(places) == []  # deux services, deux onglets
    places = [_place(1, "Lavoir de Benniget", categories=("lavoir",)), _place(2, "Lavoir de Benniget", metres=4, categories=("lavoir",), decided=True)]
    assert _found(places) == [(2, 1, duplicates.SAME_PLACE)]


def test_two_places_both_decided_by_a_human_are_only_a_doubt():
    """Deux lieux déjà tranchés par un humain ne sont jamais fusionnés par la règle : un doute (Akira, à Quimper)."""
    places = [_place(1, "Akira", decided=True), _place(2, "Akira", metres=1, decided=True)]
    assert _found(places) == [(1, 2, duplicates.DOUBT)]


def test_another_street_number_is_a_doubt_never_a_merge():
    """Dans une même source, le même nom à un autre numéro de rue est un doute, jamais une fusion (Café de la place, Camaret)."""
    places = [_place(4651, "Café de la place", "7 place Saint-Thomas, 29570 Camaret-sur-Mer", categories=("cafe",)),
              _place(4652, "Café de la place", "2 Rue Alsace-Lorraine, 29570 Camaret-sur-Mer", 1, ("cafe",))]
    assert _found(places) == [(4651, 4652, duplicates.DOUBT)]


def test_the_same_name_further_than_25_m_is_a_doubt():
    """Entre deux lieux d'OSM, le même nom à plus de 25 m est un doute (Le petit Chamarel, à 35 m)."""
    assert _found([_place(1, "Le petit Chamarel"), _place(2, "Le petit Chamarel", metres=35)]) == [(1, 2, duplicates.DOUBT)]


def test_public_toilets_merge_only_at_the_same_spot():
    """Un nom passe-partout (« Toilettes publiques ») ne fusionne qu'au même endroit : deux blocs à 15 m restent deux lieux."""
    toilets = ("toilets",)
    assert _found([_place(1, "Toilettes publiques", categories=toilets),
                   _place(2, "Toilettes publiques", metres=1, categories=toilets)]) == [(1, 2, duplicates.SAME_PLACE)]
    # Deux blocs sur une même plage restent deux lieux.
    assert _found([_place(1, "Toilettes publiques", categories=toilets),
                   _place(2, "Toilettes publiques", metres=15, categories=toilets)]) == []


def test_other_services_or_names_make_no_pair():
    """Un autre service (la pompe et le supermarché Intermarché), un autre nom ou plus de 50 m : pas de paire."""
    assert _found([_place(1, "Intermarché", categories=("fuel",)), _place(2, "Intermarché", metres=20, categories=("supermarket",))]) == []
    assert _found([_place(1, "Le Caïman"), _place(2, "Glenn Café", metres=2)]) == []
    assert _found([_place(1, "2 pignons de Kéravel"), _place(2, "2 pignons de Kéravel", metres=60)]) == []


def test_wikidata_and_osm_name_the_service_differently():
    """Wikidata et OSM ne rangent pas un lieu sous le même service : le même nom au même endroit suffit (Fort Montbarey)."""
    places = [_place(33148, "Fort Montbarey", categories=("fortification",)),
              _place(18314, "fort Montbarey", categories=("museum",), source="wikidata")]
    assert _found(places) == [(33148, 18314, duplicates.SAME_PLACE)]


def test_two_restaurant_sheets_are_left_to_the_restaurant_rule():
    """Deux restaurants qui ont chacun leur fiche sont laissés à la règle des doublons de restaurants."""
    places = [_place(1, "Racines", sheet=True, restaurant=True, categories=("restaurant",), source="agent_restaurants"),
              _place(2, "Racines", metres=2, sheet=True, restaurant=True, categories=("restaurant",), source="agent_restaurants")]
    assert _found(places) == []


def test_a_masked_place_masks_nobody_so_a_chain_does_not_vanish():
    """Trois lieux à 20 m l'un de l'autre : le deuxième est masqué au profit du premier, le troisième, à 40 m, n'est qu'un doute."""
    places = [_place(1, "Base canon"), _place(2, "Base canon", metres=20), _place(3, "Base canon", metres=40)]
    actions = {place["id"]: found for found, place, _ in duplicates.plan(duplicates.find_pairs(places))}
    assert actions == {2: duplicates.SAME_PLACE, 3: duplicates.DOUBT}


def test_a_group_keeps_a_single_place():
    """Dans un groupe, un seul lieu reste et tous les autres sont masqués à son profit (3 « Toilettes publiques », rampe de Quimper)."""
    places = [_place(id, "Toilettes publiques", metres=metres, categories=("toilets",))
              for id, metres in ((16907, 0), (16913, 1), (16914, 2))]
    actions = duplicates.plan(duplicates.find_pairs(places))
    assert [(found, place["id"]) for found, place, _ in actions] == [(duplicates.SAME_PLACE, 16913), (duplicates.SAME_PLACE, 16914)]
    assert {detail["autre_id"] for _, _, details in actions for detail in details} == {16907}


def test_the_signal_is_reviewed_in_the_duplicates_tab():
    """Le signal d'un doute se relit dans la file « Doublons » de la supervision, avec « fusionner » et « deux lieux »."""
    signal = {"id": 9, "signal_type": "doublon_service", "source": "doublons",
              "detail": {"autre_id": 9690, "autre_nom": "2 pignons de Kéravel", "autre_adresse": "Route de Saint-Mathieu",
                         "distance_m": 12, "raison": "même nom, même service"}}
    card = review.build_card("doublons", {"id": 9691, "name": "2 pignons de Kéravel"}, [signal])
    assert card["actions"][:2] == ["fusionner", "deux_lieux"] and "à 12 m" in card["preuves"][0]["texte"]
    assert review.applied_fields("fusionner", card, None) == {"masque": 1}


# --- Stations de l'État, adresses et positions d'une source à l'autre ---

def _agent(id, name, address, metres=0.0, categories=("restaurant",), **more):
    source = "agent_commerces" if more.get("shop") else "agent_restaurants"
    return _place(id, name, address, metres, categories, source, sheet=True, restaurant=not more.get("shop"), **more)


def test_the_state_station_stays_and_the_osm_one_is_masked():
    """Entre la station de la source de l'État et celle d'OSM, celle de l'État reste, même à un autre numéro (Super U de Ploudalmézeau, 47 et 37 rue de Brest)."""
    stations = [_place(1059, "Super U", "37 Rue de Brest, 29830 Ploudalmézeau", categories=("fuel",), url="https://osm.example"),
                _place(48543, "Super U", "47 Rue de Brest, 29830 Ploudalmézeau", categories=("fuel",), source="prix-carburants")]
    assert _found(stations) == [(48543, 1059, duplicates.SAME_PLACE)]


def test_a_station_and_the_shop_of_the_same_name_are_two_services():
    """La pompe du Spar et la supérette Spar créée par un agent, à 44 m, ne font pas une paire."""
    places = [_place(9374, "Spar", categories=("fuel",)), _agent(47940, "Spar", "2 rue du Port, 29217 Plougonvelin", 44, ("convenience",), shop="epicerie")]
    assert _found(places) == []


def test_between_osm_and_an_agent_the_street_number_is_no_doubt():
    """L'adresse d'OSM est souvent celle du point voisin : face à un service d'agent, un autre numéro ne fait pas un doute (Kafé Kanggui, 5 et 3 rue Louis Pasteur, à 3 m)."""
    places = [_place(450, "Kafé Kanggui", "5 Rue Louis Pasteur, 29200 Brest", categories=("cafe",)),
              _agent(32050, "Kafé Kanggui", "3 rue Louis Pasteur, 29200 Brest", 3)]
    assert _found(places) == [(32050, 450, duplicates.SAME_PLACE)]


def test_an_agent_service_is_the_same_place_up_to_50_m():
    """Un agent place un service à son adresse, pas sur son bâtiment : à 29 m du service d'OSM, c'est le même lieu (Biocoop Biogastell)."""
    places = [_place(8590, "Biocoop Biogastell", "Rue Van Gogh, 29470 Plougastel-Daoulas", categories=("supermarket",)),
              _agent(47861, "Biocoop Biogastell", "45 rue Jean Fournier, 29470 Plougastel-Daoulas", 29, ("convenience",), shop="epicerie")]
    assert _found(places) == [(47861, 8590, duplicates.SAME_PLACE)]


def test_the_cafe_of_the_shops_gives_way_to_the_restaurant_sheet():
    """Un café des commerces qui a aussi sa fiche restaurant est masqué, le restaurant reste (Dek et DEK Café)."""
    places = [_agent(32295, "DEK Café", "1 place de la Mairie, 29217 Plougonvelin"),
              _agent(47923, "Dek", "1 place de la Mairie, 29217 Plougonvelin", categories=("cafe",), shop="cafe")]
    assert _found(places) == [(32295, 47923, duplicates.SAME_PLACE)]
