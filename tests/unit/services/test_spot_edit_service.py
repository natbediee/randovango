import json
from unittest.mock import MagicMock, patch

import pytest

from services import spot_edit_service as edit
from services import supervision_service as supervision

SPOT = {"id": 1368, "name": "Parking du port", "type": "parking", "place_label": None, "city_label": "Le Conquet",
        "url": "https://p4n.fr/1368", "latitude": 48.36, "longitude": -4.77, "verifie": 1, "nuit_interdite": 0,
        "opening_period": "Avril à octobre", "ouverture_statut": "periode", "ouverture_debut": "04-01",
        "ouverture_fin": "10-31"}


@pytest.mark.parametrize("typed, stored", [("15/04", "04-15"), ("1/4", "04-01"), ("29/02", "02-29"), ("", None)])
def test_an_opening_date_is_typed_day_first(typed, stored):
    assert edit.typed_day(typed) == stored


@pytest.mark.parametrize("typed", ["31/04", "04-15", "15/13", "avril"])
def test_a_wrong_date_is_refused(typed):
    with pytest.raises(ValueError):
        edit.typed_day(typed)


def test_a_spot_without_verification_shows_as_displayed_with_its_opening():
    card = edit.spot_card(SPOT, None, None, [], None)
    assert card["statut"] == "normal" and card["verifie"] is True and card["decision_id"] is None
    assert card["ouverture"] == {"statut": "periode", "debut": "01/04", "fin": "31/10", "texte": "Avril à octobre",
                                 "decision_id": None}


def test_a_spot_removed_by_hand_shows_its_decision_to_cancel_it():
    card = edit.spot_card(SPOT, None, {"id": 55, "decision": "retirer", "verification_id": None}, ["Barrière la nuit"], 7)
    assert card["statut"] == "retire" and card["decision_id"] == 55
    assert card["a_savoir"] == "Barrière la nuit" and card["ouverture"]["decision_id"] == 7


def test_outside_a_period_the_typed_dates_are_dropped():
    with patch.object(supervision, "decide_opening") as decide:
        edit.decide_opening(1368, "toute_annee", "01/04", "31/10", "", "admin", convention=True)
    assert decide.call_args[0][:4] == (1368, "toute_annee", None, None)
    assert decide.call_args[1] == {"convention": False}


def test_a_period_keeps_its_dates_in_the_stored_form():
    with patch.object(supervision, "decide_opening") as decide:
        edit.decide_opening(1368, "periode", "01/04", "31/10", "", "admin", convention=True)
    assert decide.call_args[0][:4] == (1368, "periode", "04-01", "10-31")
    assert decide.call_args[1] == {"convention": True}


def _connected(cursor):
    connection = MagicMock()
    connection.cursor.return_value = cursor
    return patch.object(supervision.MySQLUtils, "connect", return_value=connection), \
        patch.object(supervision.MySQLUtils, "disconnect")


def test_a_spot_decision_keeps_the_badge_it_had():
    cursor = MagicMock()
    cursor.fetchone.side_effect = [{"id": None}, {"verifie": 1}]
    connect, disconnect = _connected(cursor)
    with connect, disconnect:
        supervision.decide(1368, "retirer", "", "admin")
    insert = next(call[0][1] for call in cursor.execute.call_args_list if "INSERT INTO decisions" in call[0][0])
    assert json.loads(insert[-1]) == {"avant": {"verifie": True}}


@pytest.mark.parametrize("detail, badge", [(json.dumps({"avant": {"verifie": True}}), True), (None, False)])
def test_cancelling_a_spot_decision_gives_back_the_badge_it_had(detail, badge):
    cursor = MagicMock()
    cursor.fetchone.return_value = {"objet_id": 1368, "detail": detail}
    connect, disconnect = _connected(cursor)
    with connect, disconnect:
        supervision.cancel_decision(55)
    update = next(call[0][1] for call in cursor.execute.call_args_list if call[0][0].startswith("UPDATE spots"))
    assert update == (badge, 1368)


def test_the_spots_of_a_hamlet_are_asked_by_its_name_and_its_commune():
    city = {"id": 26, "name": "Trézien", "commune": "Plouarzel", "latitude": 48.424, "longitude": -4.76797}
    cursor = MagicMock()
    cursor.fetchall.return_value = [{**SPOT, "address": None, "city_label": "Plouarzel"}]
    rows = edit._search_rows(cursor, city, "", [city])
    assert cursor.execute.call_args[0][1][-3:] == ("%Plouarzel", "Trézien", "Plouarzel")
    assert len(rows) == 1
