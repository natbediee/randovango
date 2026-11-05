from datetime import date

from services import supervision_service as supervision

TODAY = date(2026, 11, 2)
CLOSED = {"id": 10, "utilisable": "non"}
USABLE = {"id": 10, "utilisable": "oui"}


def decision(kind: str, verification_id: int = 10) -> dict:
    return {"decision": kind, "verification_id": verification_id}


def test_a_doubt_of_the_agent_waits_for_a_human() -> None:
    assert supervision.spot_status(CLOSED, None) == "propose"
    assert supervision.spot_status(USABLE, None) == "normal"
    assert supervision.spot_status(None, None) == "normal"


def test_the_human_decision_prevails_over_the_agent() -> None:
    assert supervision.spot_status(CLOSED, decision("garder")) == "garde"
    assert supervision.spot_status(CLOSED, decision("retirer")) == "retire"
    # Un retrait humain tient, même si une vérification plus récente ne voit plus de problème.
    assert supervision.spot_status(USABLE, decision("retirer", 9)) == "retire"


def test_a_newer_verification_reopens_a_kept_spot() -> None:
    # Le spot a été gardé, puis une interdiction est signalée : retour à la relecture.
    assert supervision.spot_status({"id": 11, "utilisable": "non"}, decision("garder")) == "propose"
    assert supervision.spot_status({"id": 11, "utilisable": "oui"}, decision("garder")) == "garde"


def test_in_doubt_the_traveller_does_not_see_the_spot() -> None:
    assert supervision.is_hidden("propose", None, TODAY)
    assert supervision.is_hidden("retire", None, TODAY)
    assert not supervision.is_hidden("garde", None, TODAY)
    assert not supervision.is_hidden("normal", None, TODAY)


def test_a_spot_comes_back_on_its_announced_reopening() -> None:
    assert supervision.is_hidden("propose", date(2027, 5, 1), TODAY)
    assert not supervision.is_hidden("propose", date(2027, 5, 1), date(2027, 5, 1))


def test_the_reopening_is_compared_to_the_night_of_the_trip() -> None:
    from api.routers.step3 import _night_date

    class Cursor:
        def execute(self, query, params):
            self.params = params

        def fetchone(self):
            return {"start_date": date(2027, 6, 10)}

    night = _night_date(Cursor(), 301, 3)
    assert night == date(2027, 6, 12)
    # Un camping qui rouvre en mai 2027 est proposé pour un voyage en juin 2027, pas avant.
    assert not supervision.is_hidden("propose", date(2027, 5, 1), night)
    assert _night_date(Cursor(), None, 1) == date.today()     # hors séjour


def test_a_corrected_text_is_split_into_sentences() -> None:
    assert supervision.corrected_sentences("Barre de 2 m.\n\n  Pas de services. \n") == ["Barre de 2 m.", "Pas de services."]
    assert supervision.corrected_sentences("") == []     # plus rien à signaler
