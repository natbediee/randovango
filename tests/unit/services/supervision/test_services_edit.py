import json
from unittest.mock import MagicMock

import pytest

from services.supervision import services_edit as edit

BEFORE = {"url": "https://ancien.fr", "name": "Cave Keruzas", "masque": 0, "ferme_moment": 0, "statut_saison": None,
          "mois_ouverture": None, "maps_url": None, "latitude": 48.34, "longitude": -4.71}


def _cursor(before=BEFORE, signals=()):
    cursor = MagicMock()
    cursor.fetchone.return_value = dict(before) if before else None
    cursor.fetchall.return_value = [{"id": signal_id} for signal_id in signals]
    return cursor


def _inserted_detail(cursor) -> dict:
    call = next(call for call in cursor.execute.call_args_list if "INSERT INTO decisions" in call[0][0])
    return json.loads(call[0][1][-1])


def _poi_update(cursor):
    return next((call[0] for call in cursor.execute.call_args_list if call[0][0].startswith("UPDATE poi SET")), None)


def test_a_place_without_signal_can_be_renamed_and_the_old_name_is_kept():
    cursor = _cursor()
    edit.decide_one(cursor, 32498, "autre_nom", "", "admin", name="La Cave de Keruzas")
    sql, params = _poi_update(cursor)
    assert "name = %s" in sql and params == ("La Cave de Keruzas", 32498)
    detail = _inserted_detail(cursor)
    assert detail == {"file": "modifier", "signal_ids": [], "avant": {"name": "Cave Keruzas"}}


def test_renaming_does_not_show_a_hidden_place():
    cursor = _cursor({**BEFORE, "masque": 1})
    edit.decide_one(cursor, 1, "autre_nom", "", "admin", name="Le Neuf")
    assert "masque" not in _poi_update(cursor)[0]


def test_a_google_maps_link_also_corrects_the_position():
    cursor = _cursor()
    edit.decide_one(cursor, 1, "autre_maps", "", "admin", url="https://www.google.fr/maps/@48.35,-4.72,15z")
    detail = _inserted_detail(cursor)
    assert detail["avant"] == {"maps_url": None, "latitude": 48.34, "longitude": -4.71}


def test_removing_a_place_closes_its_pending_signals_to_reopen_them_on_cancel():
    cursor = _cursor(signals=(8, 9))
    edit.decide_one(cursor, 1, "retirer", "", "admin")
    closed = next(call[0][1] for call in cursor.execute.call_args_list if "UPDATE poi_signals" in call[0][0])
    assert closed == ("valide", 8, 9)
    assert _inserted_detail(cursor)["signal_ids"] == [8, 9]


def test_a_hidden_place_can_be_put_back_but_not_removed_twice():
    assert "garder" in edit.place_actions({"masque": 1}) and "retirer" not in edit.place_actions({"masque": 1})
    with pytest.raises(ValueError):
        edit.decide_one(_cursor({**BEFORE, "masque": 1}), 1, "retirer", "", "admin")


def test_only_the_corrections_of_the_edit_tab_are_accepted():
    for action in ("valider_lien", "fusionner", "valider_pepite", "sans_suite"):
        with pytest.raises(ValueError):
            edit.decide_one(_cursor(), 1, action, "", "admin")


def test_a_link_can_be_removed_only_when_there_is_one():
    assert "retirer_lien" in edit.place_actions({"url": "https://a.fr"})
    assert "retirer_lien" not in edit.place_actions({"url": None})


def test_a_typed_link_is_still_checked():
    with pytest.raises(ValueError):
        edit.decide_one(_cursor(), 1, "autre_lien", "", "admin", url="javascript:alert(1)")


def test_an_unknown_place_is_refused():
    with pytest.raises(ValueError):
        edit.decide_one(_cursor(before=None), 1, "autre_nom", "", "admin", name="X Y")


def _row(name, category, service_name, shop=None, masque=0):
    return {"id": hash(name) % 1000, "name": name, "address": "", "url": None, "maps_url": None, "latitude": 48.3,
            "longitude": -4.7, "masque": masque, "ferme_moment": 0, "statut_saison": None, "mois_ouverture": None,
            "service_name": service_name, "service_category": category, "table_categorie": None,
            "shop_categorie": shop, "commune": "Plougonvelin"}


def test_the_filters_follow_the_step4_tabs_and_the_sheet_category():
    rows = [_row("La Cave de Keruzas", "shop", "Caviste"), _row("Laot", "bakery", "Boulangerie"),
            _row("Le Port", "cafe", "Café"), _row("Marché", "marketplace", "Marché", shop="marche", masque=1)]
    cards, by_tab, by_type = edit.filter_cards(rows, "commerce", None)
    assert by_tab["commerce"] == 3 and by_tab["cafe"] == 1
    assert {card["nom"] for card in cards} == {"La Cave de Keruzas", "Laot", "Marché"}
    assert by_type == {"Caviste": 1, "Boulangerie": 1, "Marché": 1}
    cards, _, _ = edit.filter_cards(rows, "commerce", "Marché")
    assert [card["nom"] for card in cards] == ["Marché"] and cards[0]["masque"] is True


# --- La fiche complète ---------------------------------------------------------------------------------------------

POI_ROW = {**BEFORE, "description": None, "address": "37 Rue de Bertheaume, 29217 Plougonvelin"}
SHOP = {"origine": "table", "table": "commerces",
        "values": {"genre": "cave", "pourquoi": "Vins et bières.", "categorie": "epicerie", "jours": None}}


def _sheet_cursor(poi=POI_ROW, signals=()):
    cursor = MagicMock()
    cursor.fetchone.return_value = dict(poi) if poi else None
    cursor.fetchall.return_value = list(signals)
    return cursor


def _executed(cursor, start: str):
    return [call[0] for call in cursor.execute.call_args_list if call[0][0].lstrip().startswith(start)]


def test_the_presented_text_of_an_agent_place_goes_to_its_sheet(monkeypatch):
    monkeypatch.setattr(edit, "load_sheet", lambda cursor, poi_id: SHOP)
    cursor = _sheet_cursor()
    changed = edit.decide_sheet_one(cursor, 32498, {"texte": "Cave et épicerie fine.", "genre": "cave, épicerie fine"}, "", "admin")
    assert changed == ["genre", "pourquoi"]
    sql, params = _executed(cursor, "UPDATE commerces")[0]
    assert params == ("cave, épicerie fine", "Cave et épicerie fine.", 32498)
    assert not _executed(cursor, "UPDATE poi SET")
    detail = _inserted_detail(cursor)
    assert detail["avant_fiche"] == {"origine": "table", "table": "commerces", "signal_id": None,
                                     "values": {"genre": "cave", "pourquoi": "Vins et bières."}}
    assert detail["avant"] == {} and detail["file"] == "modifier"


def test_an_osm_description_is_the_text_the_traveller_reads(monkeypatch):
    monkeypatch.setattr(edit, "load_sheet", lambda cursor, poi_id: SHOP)
    cursor = _sheet_cursor({**POI_ROW, "description": "Texte OSM"})
    assert edit.decide_sheet_one(cursor, 1, {"texte": "Nouveau texte"}, "", "admin") == ["description"]
    assert _executed(cursor, "UPDATE poi SET")[0][1] == ("Nouveau texte", 1)


def test_unchanged_fields_are_not_written_and_nothing_changed_is_refused(monkeypatch):
    monkeypatch.setattr(edit, "load_sheet", lambda cursor, poi_id: SHOP)
    with pytest.raises(ValueError, match="Rien"):
        edit.decide_sheet_one(_sheet_cursor(), 1, {"name": "Cave Keruzas", "genre": "cave"}, "", "admin")


def test_a_season_needs_its_months_when_confirmed(monkeypatch):
    monkeypatch.setattr(edit, "load_sheet", lambda cursor, poi_id: None)
    with pytest.raises(ValueError):
        edit.decide_sheet_one(_sheet_cursor(), 1, {"statut_saison": "confirmee", "mois": []}, "", "admin")
    cursor = _sheet_cursor()
    assert edit.decide_sheet_one(cursor, 1, {"statut_saison": "confirmee", "mois": [8, 3, 4, 99]}, "", "admin") == ["saison"]
    assert _executed(cursor, "UPDATE poi SET")[0][1] == ("confirmee", "[3, 4, 8]", 1)


def test_a_place_without_agent_sheet_has_no_sheet_fields(monkeypatch):
    monkeypatch.setattr(edit, "load_sheet", lambda cursor, poi_id: None)
    with pytest.raises(ValueError):
        edit.decide_sheet_one(_sheet_cursor(), 1, {"genre": "cave"}, "", "admin")


@pytest.mark.parametrize("changes", [{"categorie": "pizzeria"}, {"distinction": "Michelin"}, {"genre": ""},
                                     {"address": "<b>rue</b>"}, {"texte": "x" * 1001}, {"url": "ftp://a.fr"}])
def test_typed_sheet_fields_are_checked(monkeypatch, changes):
    monkeypatch.setattr(edit, "load_sheet", lambda cursor, poi_id: SHOP)
    with pytest.raises(ValueError):
        edit.decide_sheet_one(_sheet_cursor(), 1, changes, "", "admin")


def test_emptying_a_link_removes_it(monkeypatch):
    monkeypatch.setattr(edit, "load_sheet", lambda cursor, poi_id: None)
    cursor = _sheet_cursor()
    assert edit.decide_sheet_one(cursor, 1, {"url": ""}, "", "admin") == ["url"]
    assert _inserted_detail(cursor)["avant"] == {"url": "https://ancien.fr"}


def test_correcting_the_doubted_name_in_its_queue_closes_it_and_shows_the_place(monkeypatch):
    monkeypatch.setattr(edit, "load_sheet", lambda cursor, poi_id: None)
    cursor = _sheet_cursor({**POI_ROW, "masque": 1},
                           signals=[{"id": 4, "signal_type": "renommage_osm"}, {"id": 5, "signal_type": "lien_osm"}])
    edit.decide_sheet_one(cursor, 1, {"name": "Le Neuf"}, "", "admin", tab="fermetures")
    assert _executed(cursor, "UPDATE poi_signals")[0][1] == ("valide", 4)
    assert _executed(cursor, "UPDATE poi SET")[0][1] == ("Le Neuf", 0, 1)
    assert _inserted_detail(cursor)["signal_ids"] == [4]


def test_correcting_another_field_in_a_queue_leaves_it_to_decide(monkeypatch):
    monkeypatch.setattr(edit, "load_sheet", lambda cursor, poi_id: None)
    cursor = _sheet_cursor(signals=[{"id": 4, "signal_type": "renommage_osm"}])
    edit.decide_sheet_one(cursor, 1, {"address": "Rue du Port"}, "", "admin", tab="fermetures")
    assert not _executed(cursor, "UPDATE poi_signals")


def test_the_sheet_of_a_place_to_confirm_is_corrected_in_its_signal(monkeypatch):
    pending = {"origine": "signal", "table": "restaurants", "signal_id": 77,
               "values": {"genre": "crêperie", "pourquoi": "Galettes.", "categorie": "regionale", "distinction": None}}
    monkeypatch.setattr(edit, "load_sheet", lambda cursor, poi_id: pending)
    cursor = _sheet_cursor()
    cursor.fetchone.side_effect = [dict(POI_ROW), {"detail": json.dumps({"fiche": {"genre": "crêperie", "pourquoi": "Galettes."}})}]
    edit.decide_sheet_one(cursor, 1, {"texte": "Galettes face au port."}, "", "admin", tab="confirmer")
    detail = json.loads(_executed(cursor, "UPDATE poi_signals SET detail")[0][1][0])
    assert detail["fiche"] == {"genre": "crêperie", "pourquoi": "Galettes face au port."}
    assert _inserted_detail(cursor)["avant_fiche"]["signal_id"] == 77


def test_cancelling_a_corrected_sheet_restores_its_table():
    cursor = MagicMock()
    edit.review.restore_sheet(cursor, 32498, {"origine": "table", "table": "commerces",
                                              "values": {"pourquoi": "Vins et bières.", "name": "piège"}})
    sql, params = cursor.execute.call_args[0]
    assert sql.startswith("UPDATE commerces SET pourquoi = %s") and params == ("Vins et bières.", 32498)


def test_the_view_shows_the_text_the_traveller_reads_and_the_sheet_fields():
    view = edit.sheet_view({**POI_ROW, "id": 1, "verifie": 1, "statut_saison": "confirmee", "mois_ouverture": "[3, 4, 5]"},
                           SHOP, "Caviste")
    assert view["texte"] == "Vins et bières." and view["texte_cible"] == "pourquoi"
    assert view["type_label"] == "Épicerie, supérette" and "jours" in view["champs"] and "distinction" not in view["champs"]
    assert view["saison_label"] == "Ouvert d'avril à juin"
    osm = edit.sheet_view({**POI_ROW, "id": 2, "description": "Texte OSM"}, None, "Toilettes")
    assert osm["texte"] == "Texte OSM" and osm["type_label"] == "Toilettes" and "genre" not in osm["champs"]


def test_human_fields_tell_the_agents_what_not_to_rewrite():
    cursor = MagicMock()
    cursor.fetchall.return_value = [{"decision": "modifier_fiche", "detail": json.dumps({"champs": ["pourquoi", "address"]})},
                                    {"decision": "autre_nom", "detail": None}, {"decision": "valider_saison", "detail": "{}"},
                                    {"decision": "retirer", "detail": "{}"}]
    assert edit.human_fields(cursor, 1) == {"pourquoi", "address", "name", "saison"}


# --- La ville du filtre : celle de l'adresse -------------------------------------------------------------------------

BATZ = {"id": 47, "name": "Île-de-Batz", "latitude": 48.7409, "longitude": -4.00808}
ROSCOFF = {"id": 12, "name": "Roscoff", "latitude": 48.7262, "longitude": -3.9853}
CITIES = [BATZ, ROSCOFF]


@pytest.mark.parametrize("address, town", [("Quai Neuf, 29680 Roscoff", "Roscoff"),
                                           ("Aod ar Goz Vilin, 29253 Île-de-Batz", "Île-de-Batz"),
                                           ("Rue du Port", None), (None, None)])
def test_the_town_of_an_address_follows_its_postal_code(address, town):
    assert edit.address_town(address) == town


def test_a_place_on_the_mainland_is_not_on_the_island():
    assert not edit.in_city("Roscoff", 48.7267, -3.98117, BATZ, CITIES)
    assert edit.in_city("ILE-DE-BATZ", 48.75, -4.02, BATZ, CITIES)


def test_a_place_without_address_belongs_to_the_nearest_city():
    assert edit.in_city(None, 48.7407, -4.00789, BATZ, CITIES)       # l'abri de l'île
    assert not edit.in_city(None, 48.7267, -3.98117, BATZ, CITIES)   # sur le quai de Roscoff
    assert not edit.in_city(None, None, None, BATZ, CITIES)


def test_the_search_keeps_the_places_of_the_city_and_shows_their_town():
    cursor = MagicMock()
    cursor.fetchall.return_value = [
        {"id": 1, "name": "Abri", "address": None, "latitude": 48.7407, "longitude": -4.00789, "commune": "Cléder"},
        {"id": 2, "name": "Abri", "address": "Quai Neuf, 29680 Roscoff", "latitude": 48.7267, "longitude": -3.98117, "commune": "Île-de-Batz"},
        {"id": 3, "name": "Crêperie", "address": "Poull Zarab, 29253 Île-de-Batz", "latitude": 48.746, "longitude": -4.02, "commune": "Roscoff"}]
    rows = edit._search_rows(cursor, BATZ, "", CITIES)
    assert [(row["id"], row["commune"]) for row in rows] == [(1, "Île-de-Batz"), (3, "Île-de-Batz")]


TREZIEN = {"id": 26, "name": "Trézien", "commune": "Plouarzel", "latitude": 48.424, "longitude": -4.76797}


def test_a_hamlet_holds_the_addresses_of_its_commune():
    """Les adresses écrivent la commune (« 29810 Plouarzel »), un spot Park4Night peut écrire le lieu-dit."""
    assert edit.in_city("Plouarzel", 48.41, -4.79, TREZIEN, [TREZIEN])
    assert edit.in_city("Trézien", 48.41, -4.79, TREZIEN, [TREZIEN])
    assert not edit.in_city("Lampaul-Plouarzel", 48.44, -4.78, TREZIEN, [TREZIEN])


def test_the_search_of_a_hamlet_asks_for_its_commune_and_shows_it():
    cursor = MagicMock()
    cursor.fetchall.return_value = [{"id": 1, "name": "Abri", "address": None, "latitude": 48.42, "longitude": -4.77, "commune": None}]
    rows = edit._search_rows(cursor, TREZIEN, "", [TREZIEN])
    assert cursor.execute.call_args[0][1][4] == "%Plouarzel"
    assert rows[0]["commune"] == "Plouarzel"


def test_a_station_sheet_corrects_every_field_like_other_services():
    """Une station-service se corrige comme les autres services (nom, adresse, liens, texte, saison), avec ses prix en plus."""
    poi = {"id": 48710, "name": "Carrefour", "address": "1 rue du moulin, 29730 Guilvinec", "latitude": 47.8, "longitude": -4.2,
           "masque": 1, "verifie": 1}
    view = edit.sheet_view(poi, None, "fuel", station={"pdv_id": "29730006", "prix": []})
    assert view["champs"] == ["name", "address", "url", "maps_url", "texte", "saison"]
    assert view["station"]["pdv_id"] == "29730006"
    assert edit.sheet_view(poi, None, "Boulangerie")["station"] is None


def test_a_place_is_found_by_the_town_of_its_address():
    """Cas du Carrefour de Guilvinec : Guilvinec n'est pas une ville de l'étape 1, on le trouve par la commune de son adresse."""
    cursor = MagicMock()
    cursor.fetchall.return_value = [
        {"id": 48710, "name": "Carrefour", "address": "1 rue du moulin, 29730 Guilvinec", "latitude": 47.805, "longitude": -4.28},
        {"id": 7, "name": "Boulangerie", "address": "2 rue de Guilvinec, 29120 Plomeur", "latitude": 47.84, "longitude": -4.28}]
    rows = edit._search_rows(cursor, None, "", [], town="GUILVINEC")
    assert [(row["id"], row["commune"]) for row in rows] == [(48710, "Guilvinec")]
    assert cursor.execute.call_args.args[1] == ("%GUILVINEC",)


def test_the_towns_offered_come_with_their_postcodes():
    """La recherche propose Guilvinec (29730), commune d'une adresse ; Plomeur, ville de l'étape 1, garde son code 29120."""
    cursor = MagicMock()
    cursor.fetchall.return_value = [{"address": "1 rue du moulin, 29730 Guilvinec"}, {"address": "Bourg, 29120 PLOMEUR"},
                                    {"address": "Quai, 29730 GUILVINEC"}, {"address": "Rue sans code"}]
    city_codes, towns = edit.address_towns(cursor, [{"id": 81, "name": "Plomeur", "commune": "Plomeur"}])
    assert city_codes == {81: ["29120"]}
    assert towns == [{"nom": "Guilvinec", "codes": ["29730"]}]


def _attach_with(monkeypatch, views: dict, cards: list) -> tuple:
    """Lance attach_sheets sans base : _sheet_views rend les fiches données ; rend les cartes et les lieux demandés."""
    monkeypatch.setattr(edit.MySQLUtils, "connect", lambda: MagicMock())
    monkeypatch.setattr(edit.MySQLUtils, "disconnect", lambda c: None)
    asked = []
    monkeypatch.setattr(edit, "_sheet_views", lambda cursor, ids: asked.append(sorted(ids)) or
                        {poi_id: views[poi_id] for poi_id in ids if poi_id in views})
    return edit.attach_sheets({"cards": cards})["cards"], asked


def test_a_station_declared_twice_comes_with_the_other_station(monkeypatch):
    """Plouguerneau en supervision : la fiche de l'ancienne station arrive avec l'autre, à 9 m, et ses prix du jour."""
    views = {48528: {"poi_id": 48528, "station": {"pdv_id": "29880005"}, "position": [48.6050, -4.5040]},
             48527: {"poi_id": 48527, "station": {"pdv_id": "29880006"}, "position": [48.6050, -4.50388]}}
    cards, asked = _attach_with(monkeypatch, views, [{"poi_id": 48528, "tab": "doublons", "autre_id": 48527,
                                                      "position": [48.6050, -4.5040]}])
    assert asked == [[48528], [48527]]
    assert cards[0]["autre_lieu"]["station"] == {"pdv_id": "29880006"}
    assert cards[0]["autre_lieu"]["distance_m"] == 9


def test_a_duplicate_restaurant_comes_with_the_other_place_and_its_distance(monkeypatch):
    """« A l'Aise Breizh Café » proposé comme doublon de « Fraya » : Fraya arrive à côté, avec son adresse et sa distance."""
    fraya = {"poi_id": 2, "nom": "Fraya", "adresse": "Quai, 29217 Le Conquet", "commune": "Le Conquet",
             "type_label": "Crêperie", "url": "https://fraya.fr", "position": [48.3600, -4.7700], "station": None}
    cards, _ = _attach_with(monkeypatch, {1: {"poi_id": 1}, 2: fraya},
                            [{"poi_id": 1, "tab": "doublons", "autre_id": 2, "position": [48.3600, -4.7705]}])
    other = cards[0]["autre_lieu"]
    assert (other["nom"], other["adresse"], other["commune"], other["type_label"]) == \
           ("Fraya", "Quai, 29217 Le Conquet", "Le Conquet", "Crêperie")
    assert other["distance_m"] == 37


def test_a_card_outside_duplicates_has_no_other_place(monkeypatch):
    """Une carte d'une autre file (un lien à valider) n'a pas d'autre lieu : rien n'est cherché pour elle."""
    cards, asked = _attach_with(monkeypatch, {1: {"poi_id": 1}}, [{"poi_id": 1, "tab": "liens"}])
    assert cards[0]["autre_lieu"] is None
    assert asked == [[1], []]


def test_the_distance_is_unknown_when_a_place_has_no_position():
    """Un lieu sans position (un objet OSM sans coordonnées) : la distance n'est pas inventée, elle reste inconnue."""
    assert edit.distance_m(None, [48.36, -4.77]) is None
    assert edit.distance_m([48.36, -4.77], [48.36, -4.77]) == 0
