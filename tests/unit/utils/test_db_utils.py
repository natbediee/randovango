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
        self.options = None

    def cursor(self, **options):
        if self.cursor_fails:
            raise RuntimeError("curseur impossible à créer")
        self.options = options
        self.dictionary = options.get("dictionary", False)
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


def test_open_cursor_passes_no_option_by_default(fake_mysql) -> None:
    """Sans option, open_cursor appelle cnx.cursor() tout court, comme le code d'avant (plan_service, service_store)."""
    with MySQLUtils.open_cursor() as (cnx, _):
        pass

    assert cnx.options == {}


def test_open_cursor_can_ask_a_buffered_cursor(fake_mysql) -> None:
    """open_cursor(buffered=True) demande un curseur qui lit tout le résultat d'un coup, comme le chargement Park4Night."""
    with MySQLUtils.open_cursor(dictionary=True, buffered=True) as (cnx, _):
        pass

    assert cnx.options == {"dictionary": True, "buffered": True}


def test_every_city_pass_goes_through_the_communes_only(monkeypatch) -> None:
    """Les passages « --toutes » (pharmacies, carburants) ne repassent plus par les lieux-dits, comme Penmarc'h ou Lilia."""
    from unittest.mock import MagicMock

    from utils import db_utils
    from utils.geo_utils import communes_only

    cursor = MagicMock()
    cursor.fetchall.return_value = [(140, "Penmarch")]
    connection = MagicMock()
    connection.cursor.return_value = cursor
    monkeypatch.setattr(db_utils.MySQLUtils, "connect", lambda: connection)
    monkeypatch.setattr(db_utils.MySQLUtils, "disconnect", lambda cnx: None)

    assert db_utils.get_all_city_ids() == [(140, "Penmarch")]
    assert communes_only() in cursor.execute.call_args.args[0]
