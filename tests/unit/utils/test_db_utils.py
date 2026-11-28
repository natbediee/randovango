"""Tests de MySQLUtils.open_cursor (issue #206) : la connexion et le curseur se ferment toujours.

Cas réel : une fuite de connexions avait bloqué l'étape 3 (erreur 500, table verrouillée), parce qu'une erreur
survenait avant le disconnect. Ces tests remplacent MySQL par une fausse connexion qui note ce qu'on ferme.
"""
import pytest

from utils.db_utils import MySQLUtils

# La vraie fonction du verrou d'écriture, gardée avant que le conftest ne la remplace pour chaque test.
REAL_WRITE_LOCK = MySQLUtils.__dict__["write_lock"]


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


# --- La reprise d'une écriture annulée pour interblocage (issue #361) ---

def _deadlock():
    """L'erreur que MySQL renvoie quand il annule une transaction pour interblocage (1213)."""
    import mysql.connector
    return mysql.connector.errors.InternalError(
        msg="Deadlock found when trying to get lock; try restarting transaction", errno=1213, sqlstate="40001")


def _failing_write(errors: list, result="écrit"):
    """Une écriture qui lève, à chaque appel, l'erreur suivante de la liste, puis rend result. Note ses appels."""
    calls = []

    def write():
        calls.append(len(calls) + 1)
        if errors:
            raise errors.pop(0)
        return result
    return write, calls


@pytest.fixture
def no_wait(monkeypatch):
    """Les attentes entre deux essais ne durent pas : on note seulement leur durée."""
    from utils import db_utils
    waits = []
    monkeypatch.setattr(db_utils.time, "sleep", waits.append)
    return waits


def test_a_write_cancelled_once_for_deadlock_is_redone(no_wait) -> None:
    """Les services de Saint-Paul-sur-Ubaye, annulés une fois pendant que les carburants écrivaient : refaits, ils passent."""
    write, calls = _failing_write([_deadlock()])

    assert MySQLUtils.retry_on_deadlock(write, "les services de Saint-Paul-sur-Ubaye") == "écrit"
    assert calls == [1, 2]
    assert len(no_wait) == 1


def test_a_write_cancelled_at_every_attempt_fails_with_a_clear_message(no_wait) -> None:
    """Après trois annulations de suite, le passage échoue en nommant l'écriture et l'interblocage."""
    from utils.db_utils import DEADLOCK_ATTEMPTS, DeadlockRetriesExhausted
    write, calls = _failing_write([_deadlock() for _ in range(DEADLOCK_ATTEMPTS)])

    with pytest.raises(DeadlockRetriesExhausted) as raised:
        MySQLUtils.retry_on_deadlock(write, "les services de Donville-les-Bains")

    assert len(calls) == DEADLOCK_ATTEMPTS
    assert str(raised.value) == ("interblocage MySQL en écrivant les services de Donville-les-Bains : écriture annulée "
                                 "3 fois de suite pendant qu'une autre étape écrivait ; reprendre le passage")


def test_another_mysql_error_is_not_retried(no_wait) -> None:
    """Une autre erreur MySQL (table absente) repart tout de suite : seul l'interblocage se refait."""
    import mysql.connector
    missing = mysql.connector.errors.ProgrammingError(msg="Table 'poi' doesn't exist", errno=1146)
    write, calls = _failing_write([missing])

    with pytest.raises(mysql.connector.errors.ProgrammingError):
        MySQLUtils.retry_on_deadlock(write, "les services de Ploudalmézeau")

    assert calls == [1]
    assert no_wait == []


# --- Le verrou d'écriture commun aux étapes de la file (issue #361) ---

class LockCursor:
    """Faux curseur de la connexion du verrou : note les requêtes, et répond granted à GET_LOCK."""

    def __init__(self, granted):
        self.granted, self.queries, self.last = granted, [], ""

    def execute(self, sql, params=None):
        self.last = sql
        self.queries.append(sql.split("(")[0])

    def fetchone(self):
        return (self.granted,) if self.last.startswith("SELECT GET_LOCK") else (1,)

    def close(self):
        pass


@pytest.fixture
def lock_mysql(monkeypatch):
    """Remplace la connexion du verrou par un LockCursor qui accorde le jeton ; rend ce curseur."""
    cursor = LockCursor(granted=1)
    monkeypatch.setattr(MySQLUtils, "write_lock", REAL_WRITE_LOCK)
    monkeypatch.setattr(MySQLUtils, "connect", staticmethod(lambda: object()))
    monkeypatch.setattr(MySQLUtils, "disconnect", staticmethod(lambda cnx: None))
    monkeypatch.setattr(MySQLUtils, "get_cursor", staticmethod(lambda cnx, **options: cursor))
    return cursor


def test_a_write_takes_the_common_lock_and_gives_it_back(lock_mysql, no_wait) -> None:
    """Les carburants d'une ville écrivent sous le jeton commun, puis le rendent pour l'étape suivante."""
    assert MySQLUtils.exclusive_write(lambda: "écrit", "les carburants de Barcelonnette") == "écrit"
    assert lock_mysql.queries == ["SELECT GET_LOCK", "SELECT RELEASE_LOCK"]


def test_the_lock_is_given_back_when_the_write_fails(lock_mysql, no_wait) -> None:
    """Une écriture qui plante rend quand même le jeton : les autres étapes ne restent pas bloquées derrière elle."""
    def broken_write():
        raise RuntimeError("base injoignable")

    with pytest.raises(RuntimeError, match="base injoignable"):
        MySQLUtils.exclusive_write(broken_write, "les services de Saint-Paul-sur-Ubaye")
    assert lock_mysql.queries[-1] == "SELECT RELEASE_LOCK"


def test_a_write_waiting_too_long_for_the_lock_fails_with_a_clear_message(lock_mysql, no_wait) -> None:
    """Une étape qui attend le jeton plus de dix minutes échoue en disant ce qu'elle attendait, sans rien écrire."""
    from utils.db_utils import WriteLockTimeout
    lock_mysql.granted = 0
    writes = []

    with pytest.raises(WriteLockTimeout, match="les services de Donville-les-Bains a attendu plus de 10 min"):
        MySQLUtils.exclusive_write(lambda: writes.append("écrit"), "les services de Donville-les-Bains")
    assert writes == []


def test_a_protected_write_inside_another_does_not_ask_the_lock_again(lock_mysql, no_wait) -> None:
    """Une écriture protégée qui en appelle une autre garde le jeton : redemandé, il l'attendrait elle-même dix minutes."""
    def outer_write():
        return MySQLUtils.exclusive_write(lambda: "dedans", "les signaux d'une station")

    assert MySQLUtils.exclusive_write(outer_write, "les carburants de Barcelonnette") == "dedans"
    assert lock_mysql.queries == ["SELECT GET_LOCK", "SELECT RELEASE_LOCK"]


def test_an_exclusive_commit_writes_then_ends_the_transaction(no_wait) -> None:
    """Les écritures d'un spot ou d'une pépite passent sous le jeton puis sont commitées, avant le prochain appel de l'agent."""
    class Cursor:
        queries = []

        def execute(self, sql, params=None):
            self.queries.append(sql)

    cursor = Cursor()
    MySQLUtils.exclusive_commit(cursor, lambda: cursor.execute("UPDATE spots"), "la description du spot 1")
    assert cursor.queries == ["UPDATE spots", "COMMIT"]
