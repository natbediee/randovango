"""Étape 2 : la connexion MySQL de /hikes se ferme même quand une requête échoue (issue #206).

Cas réel : une fuite de connexions avait bloqué l'étape 3 (erreur 500, table verrouillée). Ici, une fausse
connexion fait échouer la recherche des randonnées et note si le curseur et la connexion ont été fermés.
"""
import pytest

from api.routers import step2


class _FailingCursor:
    """Faux curseur : trouve la ville, puis échoue sur la requête des randonnées."""

    def __init__(self):
        self.closed = False

    def execute(self, sql, params=None):
        if "FROM hikes" in sql:
            raise RuntimeError("Lock wait timeout exceeded")

    def fetchone(self):
        return {"latitude": 48.3378, "longitude": -4.70183, "insee": "29190"}

    def close(self):
        self.closed = True


def test_hikes_closes_connection_when_query_fails(monkeypatch) -> None:
    """Une erreur MySQL pendant la recherche des randonnées ferme quand même le curseur et la connexion."""
    cursor = _FailingCursor()
    connection = type("Connection", (), {"cursor": lambda self, dictionary=False: cursor})()
    disconnected = []
    monkeypatch.setattr(step2.MySQLUtils, "connect", staticmethod(lambda: connection))
    monkeypatch.setattr(step2.MySQLUtils, "disconnect", staticmethod(lambda cnx: disconnected.append(cnx)))

    with pytest.raises(RuntimeError, match="Lock wait timeout"):
        step2.get_hikes(city_id=2, distance_km=5)

    assert cursor.closed is True
    assert disconnected == [connection]
