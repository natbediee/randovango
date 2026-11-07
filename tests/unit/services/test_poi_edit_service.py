import json
from unittest.mock import MagicMock

import pytest

from services import poi_edit_service as edit

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
