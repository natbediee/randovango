"""
Enregistrement des choix d'un jour (services/plan_service.py, insert_or_update_plan) :
une étape ne touche qu'à son propre choix, et « sans rando » ou « autre hébergement »
vident bien la colonne en base (carte #231).

La base est remplacée par un faux curseur qui garde les requêtes reçues.
"""
import pytest

from services import plan_service

EXISTING_DAY_ID = 12


class FakeCursor:
    """Curseur qui trouve le jour déjà créé et note chaque requête."""
    def __init__(self):
        self.queries = []

    def execute(self, query, params=None):
        self.queries.append((query, params))

    def fetchone(self):
        return (EXISTING_DAY_ID,)

    def close(self):
        pass


class FakeConnection:
    """Connexion qui donne le faux curseur et accepte le commit."""
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def commit(self):
        pass


def save(monkeypatch, data: dict) -> list:
    """Enregistre `data` pour le jour existant et renvoie les mises à jour de trip_days."""
    cursor = FakeCursor()
    monkeypatch.setattr(plan_service.MySQLUtils, "connect", lambda: FakeConnection(cursor))
    monkeypatch.setattr(plan_service.MySQLUtils, "disconnect", lambda connection: None)
    plan_service.insert_or_update_plan(1, data)
    return [(query, params) for query, params in cursor.queries if query.startswith("UPDATE trip_days")]


def test_other_accommodation_clears_the_spot_of_the_day(monkeypatch) -> None:
    """« Autre hébergement » (spot_id à None) efface le spot du jour : un spot choisi avant ne reste pas en base."""
    updates = save(monkeypatch, {"spot_id": None, "day_number": 1})
    assert updates == [("UPDATE trip_days SET spot_id = %s WHERE id = %s", (None, EXISTING_DAY_ID))]


def test_no_hike_clears_the_hike_of_the_day(monkeypatch) -> None:
    """« Sans rando » (hike_id à None) efface la rando du jour, comme « autre hébergement » pour le spot."""
    updates = save(monkeypatch, {"hike_id": None, "day_number": 1})
    assert updates == [("UPDATE trip_days SET hike_id = %s WHERE id = %s", (None, EXISTING_DAY_ID))]


def test_a_chosen_spot_is_saved(monkeypatch) -> None:
    """Un spot choisi après « autre hébergement » reprend sa place en base."""
    updates = save(monkeypatch, {"spot_id": 345, "day_number": 1})
    assert updates == [("UPDATE trip_days SET spot_id = %s WHERE id = %s", (345, EXISTING_DAY_ID))]


def test_the_services_step_leaves_the_spot_and_the_hike_alone(monkeypatch) -> None:
    """L'étape 4 n'envoie que ses services : le spot et la rando du jour ne sont pas touchés."""
    assert save(monkeypatch, {"services": [7, 8], "day_number": 1}) == []


class FailingCursor(FakeCursor):
    """Curseur qui échoue à l'écriture du choix du jour, et retient s'il a été fermé."""
    def __init__(self):
        super().__init__()
        self.closed = False

    def execute(self, query, params=None):
        if query.startswith("UPDATE trip_days"):
            raise RuntimeError("Lock wait timeout exceeded")
        super().execute(query, params)

    def close(self):
        self.closed = True


def test_failed_choice_still_closes_the_connection(monkeypatch) -> None:
    """Une écriture du choix du jour qui échoue ferme quand même la connexion (fuite qui avait bloqué l'étape 3, issue #206)."""
    cursor = FailingCursor()
    connection = FakeConnection(cursor)
    disconnected = []
    monkeypatch.setattr(plan_service.MySQLUtils, "connect", lambda: connection)
    monkeypatch.setattr(plan_service.MySQLUtils, "disconnect", lambda cnx: disconnected.append(cnx))

    with pytest.raises(RuntimeError, match="Lock wait timeout"):
        plan_service.insert_or_update_plan(1, {"spot_id": 7, "day_number": 1})

    assert cursor.closed is True
    assert disconnected == [connection]
