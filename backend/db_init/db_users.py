import os
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))
from utils.logger_util import LoggerUtil
import sqlite3
from passlib.hash import bcrypt
from utils.service_utils import ServiceUtil

logger = LoggerUtil.get_logger("DB_init")

ServiceUtil.load_env()
DB_PATH = Path("/usr/src/storage/rando_users.sqlite")
ROLES = ["admin", "user", "contributor", "guest"]

# Mots de passe de seed pris dans l'environnement (.env, non versionné) : jamais en dur
# dans le code source. Le script échoue explicitement si une variable manque, plutôt que
# de retomber sur un mot de passe faible connu de quiconque lit le dépôt Git.
def _seed_password(env_var: str) -> str:
    value = os.getenv(env_var)
    if not value:
        raise RuntimeError(f"Variable d'environnement manquante pour le seed: {env_var}")
    return value

USERS = [
    ("admin", _seed_password("SEED_ADMIN_PASSWORD"), 1, ["admin"]),
    ("contributor1", _seed_password("SEED_CONTRIBUTOR1_PASSWORD"), 1, ["contributor"]),
    ("user1", _seed_password("SEED_USER1_PASSWORD"), 1, ["user"]),
    ("contributor2", _seed_password("SEED_CONTRIBUTOR2_PASSWORD"), 0, ["contributor"]),  # inactif
]

DDL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  username      TEXT    NOT NULL UNIQUE,
  password_hash TEXT    NOT NULL,
  is_active     INTEGER NOT NULL DEFAULT 1,
  created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CHECK (is_active IN (0,1))
);

CREATE TABLE IF NOT EXISTS roles (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  name       TEXT NOT NULL UNIQUE,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_role (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id    INTEGER NOT NULL,
  role_id    INTEGER NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE,
  UNIQUE (user_id, role_id)
);

CREATE TABLE IF NOT EXISTS auth_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NULL,
    username     TEXT    NULL,
    -- Plus jamais rempli (carte #61) : un jeton stocké se rejoue comme un mot de passe.
    -- La colonne reste, pour ne pas toucher à la structure d'une base existante.
    token        TEXT    NULL,
    action       TEXT    NOT NULL,
    route        TEXT    NOT NULL,
    status_code  INTEGER NOT NULL,
    ip_address   TEXT    NULL,
    access_type  TEXT    NULL,
    filename     TEXT    NULL,
    expires_at   DATETIME NULL,
    timestamp    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
);
"""


def seed(conn):
    cur = conn.cursor()
    # Roles
    for role in ROLES:
        cur.execute("INSERT OR IGNORE INTO roles(name) VALUES (?)", (role,))
    # Users
    for username, pwd, active, userole in USERS:
        cur.execute("SELECT id FROM users WHERE username=?", (username,))
        row = cur.fetchone()
        if row:
            uid = row[0]
        else:
            pwd_hash = bcrypt.hash(pwd[:72])
            cur.execute(
                "INSERT INTO users(username, password_hash, is_active) VALUES (?,?,?)",
                (username, pwd_hash, active),
            )
            uid = cur.lastrowid
        # Lier rôles
        for ur in userole:
            cur.execute("SELECT id FROM roles WHERE name=?", (ur,))
            rid = cur.fetchone()[0]
            cur.execute(
                "INSERT OR IGNORE INTO user_role(user_id, role_id) VALUES (?,?)",
                (uid, rid),
            )
    # Ajout utilisateur anonyme si absent
    cur.execute("SELECT id FROM users WHERE username=?", ("anonymous",))
    if not cur.fetchone():
        cur.execute(
            "INSERT INTO users(username, password_hash, is_active) VALUES (?,?,?)",
            ("anonymous", bcrypt.hash(""), 1),
        )
        anon_id = cur.lastrowid
        # Lier au rôle 'guest'
        cur.execute("SELECT id FROM roles WHERE name=?", ("guest",))
        rid = cur.fetchone()[0]
        cur.execute(
            "INSERT OR IGNORE INTO user_role(user_id, role_id) VALUES (?,?)",
            (anon_id, rid),
        )
    conn.commit()


def forget_stored_tokens(conn) -> int:
    """
    Efface les jetons que auth_log gardait en clair avant la carte #61 ; renvoie combien.
    Sans cela, les anciennes lignes resteraient lisibles par quiconque ouvre la base.
    Sans risque à rejouer : la seconde fois, il n'y a plus rien à effacer.
    """
    cursor = conn.execute("UPDATE auth_log SET token = NULL WHERE token IS NOT NULL")
    conn.commit()
    return cursor.rowcount


def main():
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(DDL)
        seed(conn)
        erased = forget_stored_tokens(conn)
    logger.info(f"[SQLITE] : {erased} jeton(s) effacé(s) de auth_log")
    logger.info(f"[SQLITE] : Base créée: {DB_PATH.resolve()}")


if __name__ == "__main__":
    main()
