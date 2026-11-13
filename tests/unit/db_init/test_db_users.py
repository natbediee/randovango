"""
Le journal des connexions auth_log ne garde aucun jeton (carte #61) : ni les nouvelles lignes
(services/authentification.py insert_auth_log), ni les anciennes, effacées par db_init/db_users.py.
La base SQLite est la vraie structure, créée en mémoire.
"""
import importlib
import sqlite3

import pytest

from services import authentification

SEED_VARIABLES = ("SEED_ADMIN_PASSWORD", "SEED_CONTRIBUTOR1_PASSWORD", "SEED_USER1_PASSWORD", "SEED_CONTRIBUTOR2_PASSWORD")


@pytest.fixture
def db_users(monkeypatch):
    """Le script db_users.py, qui lit les mots de passe des comptes de départ dès son import."""
    for name in SEED_VARIABLES:
        monkeypatch.setenv(name, "mot-de-passe-de-test")
    return importlib.import_module("db_init.db_users")


@pytest.fixture
def conn(db_users):
    """Une base des comptes vide, avec la vraie structure de db_users.py."""
    connection = sqlite3.connect(":memory:")
    connection.executescript(db_users.DDL)
    return connection


def stored_tokens(conn) -> list:
    return [row[0] for row in conn.execute("SELECT token FROM auth_log")]


def test_new_log_lines_hold_no_token(conn, monkeypatch):
    """Une connexion notée dans auth_log n'y laisse pas de jeton : la colonne token reste vide."""
    conn.execute("INSERT INTO users(id, username, password_hash) VALUES (7, 'camille', 'hash')")
    monkeypatch.setattr(authentification, "connect", lambda: conn)
    authentification.insert_auth_log(7, "camille", "login", "/auth/login", 200)
    assert stored_tokens(conn) == [None]


def test_old_tokens_are_erased(db_users, conn):
    """Les jetons gardés en clair avant la carte #61 sont effacés, les autres colonnes restent."""
    conn.executemany("INSERT INTO auth_log(username, token, action, route, status_code) VALUES (?, ?, 'login', '/auth/login', 200)",
                     [("camille", "eyJ.ancien.jeton"), ("louis", "eyJ.autre.jeton"), ("anne", None)])
    assert db_users.forget_stored_tokens(conn) == 2
    assert stored_tokens(conn) == [None, None, None]
    assert [row[0] for row in conn.execute("SELECT username FROM auth_log")] == ["camille", "louis", "anne"]


def test_erasing_tokens_twice_is_harmless(db_users, conn):
    """Relancer db_users.py ne fait rien de plus : la seconde fois, il n'y a plus de jeton à effacer."""
    conn.execute("INSERT INTO auth_log(username, token, action, route, status_code) VALUES ('camille', 'eyJ.jeton', 'login', '/auth/login', 200)")
    db_users.forget_stored_tokens(conn)
    assert db_users.forget_stored_tokens(conn) == 0
