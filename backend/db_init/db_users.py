
import sqlite3

from pathlib import Path
from passlib.hash import bcrypt
from backend.utils.service_utils import ServiceUtil

ROOT = Path(__file__).resolve().parents[2]
ServiceUtil.load_env()
DB_PATH = ROOT / "storage" / ServiceUtil.get_env("SQLITE_DB_NAME", "rando_users.sqlite")
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
ROLES = ["admin", "user", "contributor", "guest"]
USERS = [
    ("admin", "admin123", 1, ["admin"]),
    ("contributor1", "cont123", 1, ["contributor"]),
    ("user1", "user123", 1, ["user"]),
    ("contributor2", "cont123", 0, ["contributor"]),  # inactif
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
    token        TEXT    NULL,
    action       TEXT    NOT NULL,
    route        TEXT    NOT NULL,
    status_code  INTEGER NOT NULL,
    ip_address   TEXT    NULL,
    access_type  TEXT    NULL,
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


def main():
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(DDL)
        seed(conn)
    print(f"Base créée: {DB_PATH.resolve()}")


if __name__ == "__main__":
    main()
