"""Tests de MySQLUtils.open_cursor (issue #206) : la connexion et le curseur se ferment toujours.

Cas réel : une fuite de connexions avait bloqué l'étape 3 (erreur 500, table verrouillée), parce qu'une erreur
survenait avant le disconnect. Ces tests remplacent MySQL par une fausse connexion qui note ce qu'on ferme.
"""
import pytest

from utils.db_utils import MySQLUtils


class FakeCursor:
    """Faux curseur : retient s'il a été fermé."""

    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class FakeConnection:
    """Fausse connexion : donne un FakeCursor, ou lève une erreur si on le lui demande."""

    def __init__(self, cursor_fails=False):
        self.cursor_fails = cursor_fails
        self.last_cursor = None
        self.dictionary = None

    def cursor(self, dictionary=False):
        if self.cursor_fails:
            raise RuntimeError("curseur impossible à créer")
        self.dictionary = dictionary
        self.last_cursor = FakeCursor()
        return self.last_cursor


@pytest.fixture
def fake_mysql(monkeypatch):
    """Remplace connect et disconnect de MySQLUtils, et rend la liste des connexions fermées."""
    state = {"connection": FakeConnection(), "disconnected": []}
    monkeypatch.setattr(MySQLUtils, "connect", staticmethod(lambda: state["connection"]))
    monkeypatch.setattr(MySQLUtils, "disconnect", staticmethod(lambda cnx: state["disconnected"].append(cnx)))
    return state


def test_open_cursor_closes_everything_after_normal_block(fake_mysql) -> None:
    """Un bloc with qui se termine normalement ferme le curseur puis la connexion."""
    with MySQLUtils.open_cursor(dictionary=True) as (cnx, cursor):
        assert cnx is fake_mysql["connection"] and cursor.closed is False

    assert cursor.closed is True
    assert fake_mysql["disconnected"] == [cnx]
    assert cnx.dictionary is True


def test_open_cursor_closes_everything_when_block_raises(fake_mysql) -> None:
    """Une erreur dans le bloc with ferme quand même le curseur et la connexion (la fuite qui bloquait l'étape 3)."""
    with pytest.raises(RuntimeError, match="table verrouillée"):
        with MySQLUtils.open_cursor() as (cnx, cursor):
            raise RuntimeError("table verrouillée")

    assert cursor.closed is True
    assert fake_mysql["disconnected"] == [cnx]


def test_open_cursor_closes_connection_when_cursor_fails(fake_mysql) -> None:
    """Si le curseur ne peut pas être créé, la connexion déjà ouverte est quand même fermée."""
    fake_mysql["connection"] = FakeConnection(cursor_fails=True)

    with pytest.raises(RuntimeError, match="curseur impossible"):
        with MySQLUtils.open_cursor():
            pass

    assert fake_mysql["disconnected"] == [fake_mysql["connection"]]
