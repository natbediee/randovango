"""Tests du chargement des spots Park4Night dans MySQL (etl/load/load_p4n.py) : les connexions ouvertes se ferment.

Cas réel (issue #206) : la fonction ouvrait deux connexions et ne fermait jamais la première, même sans erreur ;
ses « return » anticipés (ville absente) laissaient aussi la seconde ouverte. Elle tourne aussi dans l'API, à l'envoi
d'un GPX, où une connexion oubliée reste prise tant que l'API tourne.
"""
import pandas as pd

from etl.load import load_p4n


class _Cursor:
    """Faux curseur : la source Park4Night existe, aucun spot n'est en base, aucune ville ne porte le nom demandé."""

    def __init__(self):
        self.closed = False
        self.last_sql = ""

    def execute(self, sql, params=None):
        self.last_sql = sql

    def fetchone(self):
        return (3,) if "FROM sources" in self.last_sql else None

    def fetchall(self):
        return []

    def close(self):
        self.closed = True


class _Connection:
    """Fausse connexion : donne un nouveau curseur à chaque demande et retient les options reçues."""

    def __init__(self):
        self.cursors = []
        self.options = []

    def cursor(self, **options):
        self.options.append(options)
        self.cursors.append(_Cursor())
        return self.cursors[-1]

    def commit(self):
        pass


def _spots() -> pd.DataFrame:
    """Un spot Park4Night transformé, comme le rend la transformation du pipeline."""
    return pd.DataFrame([{"p4n_id": "123", "Type_Place": "AIRE CC GRATUITE", "Nom_Place": "Aire du port"}])


def test_unknown_city_closes_every_opened_connection(monkeypatch) -> None:
    """Une ville absente de la base arrête le chargement, et chaque connexion ouverte est fermée (une seule est ouverte)."""
    opened, closed = [], []

    def connect():
        opened.append(_Connection())
        return opened[-1]

    monkeypatch.setattr(load_p4n.MySQLUtils, "connect", staticmethod(connect))
    monkeypatch.setattr(load_p4n.MySQLUtils, "disconnect", staticmethod(lambda cnx: closed.append(cnx)))

    load_p4n.load_p4n_to_mysql(_spots(), "Ville inconnue")

    assert len(opened) == 1
    assert closed == opened
    assert all(cursor.closed for cursor in opened[0].cursors)


def test_spots_are_read_with_a_buffered_cursor(monkeypatch) -> None:
    """Le chargement Park4Night garde son curseur bufferisé, qui lit tout le résultat d'un coup entre deux requêtes."""
    connection = _Connection()
    monkeypatch.setattr(load_p4n.MySQLUtils, "connect", staticmethod(lambda: connection))
    monkeypatch.setattr(load_p4n.MySQLUtils, "disconnect", staticmethod(lambda cnx: None))

    load_p4n.load_p4n_to_mysql(_spots(), "Ville inconnue")

    assert connection.options == [{"buffered": True}]


def test_spots_cancelled_for_deadlock_are_loaded_again(deadlocked_base) -> None:
    """Le chargement des spots d'une ville, annulé par MySQL pendant qu'une autre étape écrit, est refait au second essai."""
    # Un spot où l'on ne peut pas dormir : il est écarté, la transaction va droit au commit.
    day_only = pd.DataFrame([{"p4n_id": "124", "Type_Place": "PARKING JOUR UNIQUEMENT", "Nom_Place": "Parking du port"}])

    load_p4n.load_p4n_to_mysql(day_only, "Le Conquet")

    assert deadlocked_base.commit.call_count == 2
