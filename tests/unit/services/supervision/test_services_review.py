import json
from unittest.mock import MagicMock

import pytest

from services.supervision import decisions
from services.supervision import services_review as review


def signal(kind, source="osm", **detail):
    return {"id": 1, "signal_type": kind, "source": source, "detail": json.dumps(detail)}


POI = {"id": 7, "name": "Mary Stuart", "address": "66 Avenue de la Mer", "service": "Restaurant", "url": None}


def test_a_takeover_proposes_to_rename_with_every_source() -> None:
    signals = [signal("fermeture_osm", "osm", nom_osm=None),
               signal("fermeture_agent", "agent", type="reprise", citation="clap de fin", autre_nom="La Petite Folie", page="https://presse.fr/a")]

    card = review.build_card("fermetures", POI, signals)

    assert card["new_name"] == "La Petite Folie"
    assert card["actions"] == ["renommer", "retirer", "garder", "autre_nom", "autre_lien", "autre_maps"]
    assert card["signal"] == "Fermeture signalée"
    assert [proof["source"] for proof in card["preuves"]] == ["Agent", "OSM"]
    assert "clap de fin" in card["preuves"][0]["texte"]
    assert card["link"] == "https://presse.fr/a"


def test_an_osm_rename_proposes_its_name() -> None:
    assert review.build_card("fermetures", POI, [signal("renommage_osm", "osm", nom_osm="Kairos")])["new_name"] == "Kairos"


def test_a_temporary_closure_can_be_recorded() -> None:
    card = review.build_card("fermetures", POI, [signal("fermeture_agent", "agent", type="momentanee", citation="Fermeture temporaire")])
    assert "fermer_moment" in card["actions"]


def test_checked_link_goes_to_the_batch_and_social_does_not() -> None:
    checked = review.build_card("liens", POI, [signal("lien_agent", "agent", url="https://a.fr", type_page="site", verdict="ok", niveau="auto")])
    social = review.build_card("liens", POI, [signal("lien_agent", "agent", url="https://facebook.com/a", type_page="facebook",
                                                     verdict="a_valider_social", niveau="a_valider")])
    assert checked["auto"] is True
    assert social["auto"] is False


def test_the_agent_link_comes_before_the_osm_link() -> None:
    card = review.build_card("liens", POI, [signal("lien_osm", "osm", url="https://osm.fr"),
                                            signal("lien_agent", "agent", url="https://agent.fr", verdict="ok", niveau="auto")])
    assert card["url"] == "https://agent.fr"


def test_another_name_is_offered_only_when_the_page_shows_it() -> None:
    other = review.build_card("liens", POI, [signal("lien_agent", "agent", url="https://a.fr", verdict="a_valider_nom",
                                                    niveau="a_valider", autre_nom="Le Protis")])
    same = review.build_card("liens", POI, [signal("lien_agent", "agent", url="https://a.fr", verdict="ok", niveau="auto", autre_nom="Trebor")])
    assert other["actions"][0] == "valider_lien_nom"
    assert same["actions"] == ["valider_lien", "refuser_lien", "retirer", "autre_nom", "autre_lien", "autre_maps"]


def test_season_from_osm_gives_the_months() -> None:
    card = review.build_card("saison", POI, [signal("saison_osm", "osm", mois=["Apr", "May"], opening_hours="Apr-May")])
    assert card["months"] == [3, 4]
    assert card["statut"] == "confirmee"


def test_applied_fields_take_the_link_from_the_signal() -> None:
    card = {"url": "https://a.fr", "autre_nom": "Le Protis", "new_name": "La Petite Folie"}
    assert review.applied_fields("valider_lien", card, None) == {"url": "https://a.fr"}
    assert review.applied_fields("valider_lien_nom", card, None) == {"url": "https://a.fr", "name": "Le Protis"}
    assert review.applied_fields("renommer", card, None) == {"name": "La Petite Folie", "masque": 0}
    assert review.applied_fields("retirer", card, None) == {"masque": 1}
    assert review.applied_fields("retirer_lien", card, None) == {"url": None}
    assert review.applied_fields("garder", card, None) == {"masque": 0}
    assert review.applied_fields("refuser_lien", card, None) == {}


def test_season_without_months_stays_probable() -> None:
    fields = review.applied_fields("valider_saison", {}, [])
    assert fields["statut_saison"] == "probable"
    assert json.loads(fields["mois_ouverture"]) == []


def test_season_months_are_validated() -> None:
    fields = review.applied_fields("valider_saison", {}, [8, 3, 3, 99, "x"])
    assert fields["statut_saison"] == "confirmee"
    assert json.loads(fields["mois_ouverture"]) == [3, 8]


def test_only_links_can_be_decided_in_batch() -> None:
    with pytest.raises(ValueError):
        review.decide("fermetures", [1, 2], "retirer", "", "admin")
    with pytest.raises(ValueError):
        review.decide("liens", [1], "inconnue", "", "admin")


def test_every_action_has_its_wording() -> None:
    # La fiche corrigée à la main (services_edit.decide_sheet) a son libellé, mais son propre formulaire, pas de bouton.
    assert set(review.ACTIONS) == set(review.ACTION_LABELS) - {"modifier_fiche"} == set(review.ACTION_BUTTONS) | set(review.RULE_ACTIONS)
    assert set(review.APPLIED_COLUMNS) >= {"url", "name", "masque"}


def _to_confirm(sheet):
    return {"id": 3, "signal_type": "a_confirmer", "source": "agent_restaurants",
            "detail": {"raison": "registre : débit de boissons, dit servir des repas par les recherches",
                       "indice": "Bar-tabac-brasserie du bourg.", "page": "https://iroise-bretagne.bzh/x", "fiche": sheet}}


def test_a_place_to_confirm_shows_why_and_can_be_confirmed():
    card = review.build_card("confirmer", {"id": 32485, "name": "Le Neuf"}, [_to_confirm({"genre": "bar-tabac brasserie"})])
    assert card["actions"] == ["valider_pepite", "retirer", "autre_nom", "autre_lien", "autre_maps"] and "débit de boissons" in card["preuves"][0]["texte"]
    assert review.applied_fields("valider_pepite", card, None) == {"masque": 0}


def test_a_place_without_a_prepared_sheet_can_only_be_removed():
    card = review.build_card("confirmer", {"id": 1, "name": "Au Coin du Feu"}, [_to_confirm(None)])
    assert card["actions"] == ["retirer", "autre_nom", "autre_lien", "autre_maps"]


def test_a_rule_only_decision_cannot_come_from_the_page():
    with pytest.raises(ValueError):
        review.decide("liens", [1], "sans_suite", "", "admin")


def test_a_better_link_found_by_hand_replaces_the_proposed_one():
    signal = {"id": 4, "signal_type": "lien_agent", "source": "agent",
              "detail": {"url": "https://annuaire.fr/x", "niveau": "a_valider", "verdict": "a_valider_social", "type_page": "facebook"}}
    card = review.build_card("liens", {"id": 1, "name": "Le Neuf"}, [signal])
    assert "autre_lien" in card["actions"]
    assert review.applied_fields("autre_lien", card, None, " https://leneuf-ploudalmezeau.fr/ ") == {"url": "https://leneuf-ploudalmezeau.fr/"}


@pytest.mark.parametrize("url", [None, "", "leneuf.fr", "javascript:alert(1)", "https://a b.fr", 'https://x.fr/"><script>'])
def test_a_typed_link_must_be_a_full_web_address(url):
    with pytest.raises(ValueError):
        review.typed_link(url)


def test_a_name_found_by_hand_renames_the_place_and_shows_it():
    card = review.build_card("fermetures", POI, [signal("fermeture_agent", "agent", type="reprise", autre_nom="Le Triskell")])
    assert "autre_nom" in card["actions"]
    assert review.applied_fields("autre_nom", card, None, None, "  Le Neuf  ") == {"name": "Le Neuf", "masque": 0}


@pytest.mark.parametrize("name", [None, "", "x", "<b>Le Neuf</b>", "a" * 151])
def test_a_typed_name_must_be_short_plain_text(name):
    with pytest.raises(ValueError):
        review.typed_name(name)


def test_a_link_added_from_the_name_tab_leaves_the_name_to_decide():
    cursor = MagicMock()
    cursor.fetchall.return_value = [{"id": 8, "poi_id": 2686, "source": "osm", "signal_type": "renommage_osm",
                                     "detail": json.dumps({"nom_osm": "Jeanne et Quentin"})}]
    cursor.fetchone.return_value = {"url": None, "name": "Jeanne et Quentin", "masque": 0, "ferme_moment": 0,
                                    "statut_saison": None, "mois_ouverture": None}
    review.decide_one(cursor, "fermetures", 2686, "autre_lien", "", "admin", None, "https://jeanneetquentin.fr")
    sql = [call[0][0] for call in cursor.execute.call_args_list]
    assert any("UPDATE poi SET url" in query for query in sql)
    assert not any("UPDATE poi_signals" in query for query in sql)


def test_every_card_offers_a_typed_name_and_link():
    for tab, kind in (("liens", "lien_osm"), ("saison", "saison_osm"), ("morts", "lien_mort"), ("fermetures", "absent_osm")):
        card = review.build_card(tab, POI, [signal(kind, "osm")])
        assert card["actions"][-3:] == ["autre_nom", "autre_lien", "autre_maps"], tab


def test_every_card_can_remove_the_place():
    # Une bijouterie classée supérette se voit dans la file Liens : la retirer doit se faire de là (7 novembre 2026).
    for tab, kind in (("liens", "lien_osm"), ("saison", "saison_osm"), ("morts", "lien_mort"), ("fermetures", "absent_osm")):
        card = review.build_card(tab, POI, [signal(kind, "osm")])
        assert "retirer" in card["actions"], tab
        assert review.applied_fields("retirer", card, None) == {"masque": 1}


def test_a_removed_place_leaves_every_queue():
    cursor = MagicMock()
    cursor.fetchall.side_effect = [
        [{"id": 8, "poi_id": 2686, "source": "osm", "signal_type": "lien_osm", "detail": json.dumps({"url": "https://a.fr"})}],
        [{"id": 8}, {"id": 9}],   # tous les signaux à relire du lieu, dont un d'une autre file
    ]
    cursor.fetchone.return_value = {"url": None, "name": "Bijouterie Roudot", "masque": 0, "ferme_moment": 0,
                                    "statut_saison": None, "mois_ouverture": None}
    review.decide_one(cursor, "liens", 2686, "retirer", "", "admin", None)
    closed = next(call[0][1] for call in cursor.execute.call_args_list if "UPDATE poi_signals" in call[0][0])
    assert closed == ("valide", 8, 9)
    detail = json.loads(next(call[0][1][-1] for call in cursor.execute.call_args_list if "INSERT INTO decisions" in call[0][0]))
    assert detail["signal_ids"] == [8, 9] and detail["avant"] == {"masque": 0}


def test_a_name_typed_outside_the_name_tab_does_not_show_a_hidden_place():
    card = review.build_card("confirmer", POI, [_to_confirm(None)])
    assert review.applied_fields("autre_nom", card, None, None, "Le Neuf") == {"name": "Le Neuf"}


def test_the_filter_follows_the_step4_tabs_and_the_sheet_category():
    rows = [{"id": 1, "poi_id": 10, "source": "agent", "signal_type": "lien_agent", "detail": "{}", "p_id": 10, "name": "Laot",
             "address": "", "url": None, "latitude": None, "longitude": None, "service_name": "Boulangerie",
             "service_category": "bakery", "table_categorie": None, "shop_categorie": None, "commune": "Plougonvelin"},
            {"id": 2, "poi_id": 11, "source": "agent", "signal_type": "lien_agent", "detail": "{}", "p_id": 11, "name": "Marché",
             "address": "", "url": None, "latitude": None, "longitude": None, "service_name": "Marché",
             "service_category": "marketplace", "table_categorie": None, "shop_categorie": "marche", "commune": "Plougonvelin"},
            {"id": 3, "poi_id": 12, "source": "agent", "signal_type": "lien_agent", "detail": "{}", "p_id": 12, "name": "Le Port",
             "address": "", "url": None, "latitude": None, "longitude": None, "service_name": "Café",
             "service_category": "cafe", "table_categorie": None, "shop_categorie": None, "commune": "Plougonvelin"}]
    cursor = MagicMock()
    cursor.fetchall.return_value = rows
    _, pois = review._pending(cursor, "commerce", None)
    assert {poi["name"]: poi["service"] for poi in pois.values()} == {"Laot": "Boulangerie", "Marché": "Marché"}
    _, pois = review._pending(cursor, "commerce", None, kind="Marché")
    assert [poi["name"] for poi in pois.values()] == ["Marché"]
    _, pois = review._pending(cursor, "cafe", None)
    assert [poi["onglet"] for poi in pois.values()] == ["cafe"]


@pytest.mark.parametrize("url, position", [
    ("https://www.google.com/maps/place/Laverie/@48.3424,-4.7231,17z/data=!3m1!4b1!4m6!3m5!1s0x0:0x0!8m2!3d48.34245!4d-4.72313",
     (48.34245, -4.72313)),
    ("https://www.google.fr/maps/@48.35,-4.72,15z", (48.35, -4.72)),
    ("https://maps.app.goo.gl/AbCdEf123", None),
])
def test_a_google_maps_link_typed_by_hand_also_gives_the_position(url, position):
    fields = review.applied_fields("autre_maps", {"tab": "liens"}, None, url)
    assert fields["maps_url"] == url
    assert ((fields["latitude"], fields["longitude"]) if "latitude" in fields else None) == position


@pytest.mark.parametrize("url", ["https://exemple.fr/maps", "https://www.google.com/search?q=laverie", "maps.app.goo.gl/x"])
def test_only_a_google_maps_link_is_accepted(url):
    with pytest.raises(ValueError):
        review.applied_fields("autre_maps", {"tab": "liens"}, None, url)


def test_a_google_maps_link_closes_no_queue():
    card = review.build_card("liens", {"id": 1, "name": "Laverie"}, [
        {"id": 4, "signal_type": "lien_agent", "source": "agent", "detail": {"url": "https://x.fr", "niveau": "a_valider"}}])
    assert "autre_maps" in card["actions"] and review.SIDE_ACTIONS["autre_maps"] is None


def test_an_apostrophe_in_a_typed_link_is_encoded_not_refused():
    url = "https://www.google.com/maps/place/A+Fleur+d'Eau/@48.09,-4.33,17z"
    assert review.typed_link(url) == "https://www.google.com/maps/place/A+Fleur+d%27Eau/@48.09,-4.33,17z"
    assert review.typed_maps_link(url)["latitude"] == 48.09
    with pytest.raises(ValueError):
        review.typed_link("https://a.fr/<script>")


def test_a_doubtful_station_can_be_kept_or_removed():
    """Une station muette arrive dans « À confirmer », masquée : Garder la réaffiche, Retirer la laisse masquée."""
    card = review.build_card("confirmer", {"id": 48710, "name": "Carrefour"},
                             [signal("station_muette", source="carburants_etat", raison="rien déclaré à l'État depuis le 25/09/2026")])
    assert card["actions"][:2] == ["garder", "retirer"]
    assert card["preuves"][0] == {"source": "État", "texte": "rien déclaré à l'État depuis le 25/09/2026."}
    assert review.applied_fields("garder", card, None) == {"masque": 0}


def test_a_station_declared_twice_can_be_merged_or_shown_again():
    """Plouguerneau : la station muette, déjà masquée, se fusionne avec l'active ; « Deux lieux » la réaffiche."""
    card = review.build_card("doublons", {"id": 48528, "name": "Carrefour Contact"},
                             [signal("doublon_station", source="carburants_etat", raison="rien déclaré depuis le 21/09/2026",
                                     distance_m=9, autre_id=48527, autre_nom="Carrefour Contact")])
    assert card["signal"] == "Station déclarée deux fois" and "à 9 m de" in card["preuves"][0]["texte"]
    assert review.applied_fields("fusionner", card, None) == {"masque": 1}
    assert review.applied_fields("deux_lieux", card, None) == {"masque": 0}


def test_two_places_of_an_ordinary_duplicate_change_nothing():
    """Un doublon ordinaire n'était pas masqué : « Deux lieux » ne change rien au lieu."""
    card = review.build_card("doublons", POI, [signal("doublon_service", source="doublons", raison="même nom", autre_nom="X")])
    assert review.applied_fields("deux_lieux", card, None) == {}


def test_the_review_keeps_the_places_of_the_chosen_address_town():
    """Relecture filtrée sur Guilvinec (commune d'adresse, pas une ville de l'étape 1) : seul le Carrefour de Guilvinec reste."""
    row = {"id": 1, "p_id": 48710, "poi_id": 48710, "source": "carburants_etat", "signal_type": "station_muette",
           "detail": "{}", "name": "Carrefour", "address": "1 rue du moulin, 29730 GUILVINEC", "url": None,
           "latitude": 47.8, "longitude": -4.28, "maps_url": None, "service_name": "fuel", "service_category": "fuel",
           "table_categorie": None, "shop_categorie": None, "commune": "Plomeur"}
    other = {**row, "id": 2, "p_id": 7, "poi_id": 7, "address": "Bourg, 29120 Plomeur"}
    cursor = MagicMock()
    cursor.fetchall.return_value = [row, other]
    groups, pois = review._pending(cursor, None, None, town="Guilvinec")
    assert list(pois) == [48710] and list(groups) == [("confirmer", 48710)]


# --- Un lieu mixte : une fiche restaurant d'un côté, une fiche commerce de l'autre ---

PHARE_DOUBT = {"id": 31, "poi_id": 32496, "source": "doublons", "signal_type": "doublon_service",
               "detail": json.dumps({"autre_id": 30745, "autre_nom": "La Maison du Phare", "distance_m": 0,
                                     "raison": "même nom, deux fiches d'agent"})}
BEFORE = {"url": None, "name": "La Maison du Phare", "masque": 0, "ferme_moment": 0, "statut_saison": None, "mois_ouverture": None}


def _sheets(restaurants, commerces):
    """Ce que les tables de fiches rendent pour les deux lieux d'un doublon : restaurants, puis commerces."""
    return [[{"poi_id": poi_id} for poi_id in restaurants], [{"poi_id": poi_id} for poi_id in commerces]]


def test_a_mixed_place_needs_a_restaurant_sheet_and_a_shop_sheet():
    """« Lieu mixte » n'est possible qu'entre une fiche restaurant et une fiche commerce (La Maison du Phare), pas entre deux fiches de la même table ni sans fiche."""
    cursor = MagicMock()
    cursor.fetchall.side_effect = _sheets([30745], [32496])
    assert review.mixed_sheet_table(cursor, 32496, 30745) == "commerces"
    cursor.fetchall.side_effect = _sheets([30745, 32496], [])
    assert review.mixed_sheet_table(cursor, 32496, 30745) is None
    cursor.fetchall.side_effect = _sheets([30745], [])
    assert review.mixed_sheet_table(cursor, 32496, 30745) is None


def test_a_mixed_place_gives_its_sheet_and_services_to_the_other_and_is_masked():
    """« Lieu mixte » sur La Maison du Phare : la fiche boulangerie et le service bakery passent au restaurant, la ligne en double est masquée, et la décision garde de quoi l'annuler."""
    cursor = MagicMock()
    cursor.fetchall.side_effect = [[PHARE_DOUBT], *_sheets([30745], [32496]), [{"service_id": 12}]]
    cursor.fetchone.return_value = BEFORE
    review.decide_one(cursor, "doublons", 32496, "lieu_mixte", "", "admin", None)
    calls = [(" ".join(call[0][0].split()), call[0][1] if len(call[0]) > 1 else None) for call in cursor.execute.call_args_list]
    assert ("UPDATE commerces SET poi_id = %s WHERE poi_id = %s", (30745, 32496)) in calls
    assert ("INSERT INTO poi_service (poi_id, service_id) VALUES (%s, %s)", (30745, 12)) in calls
    assert ("UPDATE poi SET masque = %s WHERE id = %s", (1, 32496)) in calls
    detail = json.loads(next(params[-1] for sql, params in calls if sql.startswith("INSERT INTO decisions")))
    assert detail["lieu_mixte"] == {"vers": 30745, "table": "commerces", "services": [12]} and detail["avant"] == {"masque": 0}


def test_a_mixed_place_is_refused_between_two_restaurant_sheets():
    """Deux fiches restaurant au même nom ne font pas un lieu mixte : la décision est refusée, rien n'est écrit."""
    cursor = MagicMock()
    cursor.fetchall.side_effect = [[PHARE_DOUBT], *_sheets([30745, 32496], [])]
    with pytest.raises(ValueError):
        review.decide_one(cursor, "doublons", 32496, "lieu_mixte", "", "admin", None)
    assert not any("UPDATE" in call[0][0] for call in cursor.execute.call_args_list)


def test_cancelling_a_mixed_place_gives_back_the_sheet_and_the_services(monkeypatch):
    """Annuler « Lieu mixte » rend la fiche boulangerie à son lieu, retire au restaurant le service reçu et rouvre le doute."""
    connection = MagicMock()
    cursor = connection.cursor.return_value
    detail = {"file": "doublons", "signal_ids": [31], "avant": {"masque": 0},
              "lieu_mixte": {"vers": 30745, "table": "commerces", "services": [12]}}
    cursor.fetchone.return_value = {"objet_type": "poi", "objet_id": 32496, "detail": json.dumps(detail)}
    monkeypatch.setattr(review.MySQLUtils, "connect", lambda: connection)
    monkeypatch.setattr(review.MySQLUtils, "disconnect", lambda connection: None)
    decisions.cancel_decision(5)
    calls = [(" ".join(call[0][0].split()), call[0][1] if len(call[0]) > 1 else None) for call in cursor.execute.call_args_list]
    assert ("UPDATE poi SET masque = %s WHERE id = %s", (0, 32496)) in calls
    assert ("UPDATE commerces SET poi_id = %s WHERE poi_id = %s", (32496, 30745)) in calls
    assert ("DELETE FROM poi_service WHERE poi_id = %s AND service_id = %s", (30745, 12)) in calls


def test_the_mixed_place_button_comes_first_on_its_card():
    """Sur le doute d'un lieu mixte, « Lieu mixte » est proposé en premier, avant « Garder ce lieu » (des deux côtés) et « Deux lieux »."""
    card = review.build_card("doublons", {"id": 32496, "name": "La Maison du Phare"}, [PHARE_DOUBT])
    review.offer_mixed_place(card)
    assert card["actions"][:4] == ["lieu_mixte", "garder_celui_ci", "fusionner", "deux_lieux"]
    assert card["boutons"][0]["action"] == "lieu_mixte" and "Lieu mixte" in card["proposal"]


# --- « Garder ce lieu » : on choisit lequel des deux lieux d'un doublon reste ---

BREIZH_DOUBT = {"id": 41, "poi_id": 1201, "source": "doublons", "signal_type": "doublon_service",
                "detail": json.dumps({"autre_id": 1187, "autre_nom": "Fraya", "distance_m": 40, "raison": "même adresse"})}
STATION_DOUBT = {"id": 42, "poi_id": 48528, "source": "carburants_etat", "signal_type": "doublon_station",
                 "detail": json.dumps({"autre_id": 48527, "autre_nom": "Carrefour Contact", "distance_m": 9})}


def _calls(cursor) -> list:
    """Les requêtes passées au curseur, sans les retours à la ligne, avec leurs paramètres."""
    return [(" ".join(call[0][0].split()), call[0][1] if len(call[0]) > 1 else None) for call in cursor.execute.call_args_list]


def _decision(cursor) -> tuple:
    """La décision enregistrée : (lieu, nom de la décision, detail)."""
    params = next(params for sql, params in _calls(cursor) if sql.startswith("INSERT INTO decisions"))
    return params[1], params[2], json.loads(params[-1])


def test_a_duplicate_card_offers_to_keep_either_place():
    """« A l'Aise Breizh Café » proposé comme doublon de « Fraya » : on peut garder l'un ou l'autre, ou dire « Deux lieux »."""
    card = review.build_card("doublons", {"id": 1201, "name": "A l'Aise Breizh Café"}, [BREIZH_DOUBT])
    assert card["actions"][:3] == ["garder_celui_ci", "fusionner", "deux_lieux"]
    assert card["autre_id"] == 1187


def test_a_duplicate_without_the_other_number_only_offers_to_hide_this_one():
    """Un ancien doute sans numéro de l'autre lieu : impossible de le masquer ou de le retirer, seul « fusionner » (masquer celui-ci) reste."""
    card = review.build_card("doublons", POI, [signal("doublon_service", source="doublons", autre_nom="X")])
    assert "garder_celui_ci" not in card["actions"] and "retirer_les_deux" not in card["actions"]
    assert "fusionner" in card["actions"]


def test_keeping_the_card_place_hides_the_other_and_records_the_merge_on_it():
    """Garder « A l'Aise Breizh Café » masque « Fraya » ; la décision « fusionner » est enregistrée sur Fraya, le lieu masqué."""
    cursor = MagicMock()
    cursor.fetchall.side_effect = [[BREIZH_DOUBT], [{"id": 1201, "masque": 0}, {"id": 1187, "masque": 0}]]
    review.decide_one(cursor, "doublons", 1201, "garder_celui_ci", "même crêperie", "admin", None)
    calls = _calls(cursor)
    assert ("UPDATE poi SET masque = %s WHERE id = %s", (1, 1187)) in calls
    assert not any(params and params[-1] == 1201 for sql, params in calls if sql.startswith("UPDATE poi SET"))
    objet_id, decision, detail = _decision(cursor)
    assert (objet_id, decision) == (1187, "fusionner")
    assert detail == {"file": "doublons", "signal_ids": [41], "avant": {"masque": 0}, "garde": {"poi_id": 1201, "avant": {}}}


def test_keeping_the_other_place_is_still_the_merge_of_this_one():
    """Garder « Fraya » (le bouton sous l'autre lieu) fait ce que faisait « Fusionner » : A l'Aise Breizh Café est masqué."""
    cursor = MagicMock()
    cursor.fetchall.return_value = [BREIZH_DOUBT]
    cursor.fetchone.return_value = {"url": None, "name": "A l'Aise Breizh Café", "masque": 0}
    review.decide_one(cursor, "doublons", 1201, "fusionner", "", "admin", None)
    assert ("UPDATE poi SET masque = %s WHERE id = %s", (1, 1201)) in _calls(cursor)
    assert _decision(cursor)[:2] == (1201, "fusionner")


def test_keeping_a_frozen_station_shows_it_again_and_hides_the_other():
    """Plouguerneau : garder la station figée (masquée en attendant) la réaffiche et masque l'autre, qui porte la décision."""
    cursor = MagicMock()
    cursor.fetchall.side_effect = [[STATION_DOUBT], [{"id": 48528, "masque": 1}, {"id": 48527, "masque": 0}]]
    review.decide_one(cursor, "doublons", 48528, "garder_celui_ci", "", "admin", None)
    calls = _calls(cursor)
    assert ("UPDATE poi SET masque = %s WHERE id = %s", (1, 48527)) in calls
    assert ("UPDATE poi SET masque = %s WHERE id = %s", (0, 48528)) in calls
    objet_id, _, detail = _decision(cursor)
    assert objet_id == 48527 and detail["garde"] == {"poi_id": 48528, "avant": {"masque": 1}}


def test_cancelling_keep_this_place_puts_both_places_back(monkeypatch):
    """Annuler la garde de la station figée : l'autre station est réaffichée, la figée redevient masquée, le doute rouvert."""
    connection = MagicMock()
    cursor = connection.cursor.return_value
    detail = {"file": "doublons", "signal_ids": [42], "avant": {"masque": 0}, "garde": {"poi_id": 48528, "avant": {"masque": 1}}}
    cursor.fetchone.return_value = {"objet_type": "poi", "objet_id": 48527, "detail": json.dumps(detail)}
    monkeypatch.setattr(review.MySQLUtils, "connect", lambda: connection)
    monkeypatch.setattr(review.MySQLUtils, "disconnect", lambda connection: None)
    decisions.cancel_decision(9)
    calls = _calls(cursor)
    assert ("UPDATE poi SET masque = %s WHERE id = %s", (0, 48527)) in calls
    assert ("UPDATE poi SET masque = %s WHERE id = %s", (1, 48528)) in calls
    assert ("UPDATE poi_signals SET statut = 'a_relire', reviewed_at = NULL WHERE id IN (%s)", (42,)) in calls


def test_a_duplicate_card_offers_to_remove_both_places():
    """Rarement, aucun des deux n'est à garder : la carte d'« A l'Aise Breizh Café » propose aussi « Aucun des deux »."""
    card = review.build_card("doublons", {"id": 1201, "name": "A l'Aise Breizh Café"}, [BREIZH_DOUBT])
    assert "retirer_les_deux" in card["actions"]


def test_removing_both_places_hides_each_with_its_own_decision():
    """« Aucun des deux » : A l'Aise Breizh Café et Fraya sont masqués, chacun avec sa décision « retirer », annulable à part."""
    cursor = MagicMock()
    cursor.fetchall.side_effect = [[BREIZH_DOUBT], [BREIZH_DOUBT], [{"id": 41}], [{"id": 77}]]
    cursor.fetchone.side_effect = [{"url": None, "name": "A l'Aise Breizh Café", "masque": 0}, {"masque": 0}]
    review.decide_one(cursor, "doublons", 1201, "retirer_les_deux", "fermé", "admin", None)
    calls = _calls(cursor)
    assert ("UPDATE poi SET masque = %s WHERE id = %s", (1, 1201)) in calls
    assert ("UPDATE poi SET masque = %s WHERE id = %s", (1, 1187)) in calls
    decisions = [(params[1], params[2], json.loads(params[-1])) for sql, params in calls if sql.startswith("INSERT INTO decisions")]
    assert [(objet_id, decision) for objet_id, decision, _ in decisions] == [(1201, "retirer"), (1187, "retirer")]
    assert decisions[1][2] == {"file": "doublons", "signal_ids": [77], "avant": {"masque": 0}}
