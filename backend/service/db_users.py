
import sqlite3

from pathlib import Path
from passlib.hash import bcrypt

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "db" / "quiz_users.sqlite"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
ROLES = ["admin", "teacher", "student"]
USERS = [
    ("admin", "admin123", 1, ["admin"]),
    ("teacher1", "teach123", 1, ["teacher"]),
    ("student1", "stud123", 1, ["student"]),
    ("teacher2", "teach123", 0, ["teacher"]),  # inactif
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
  action       TEXT    NOT NULL,
  route        TEXT    NOT NULL,
  status_code  INTEGER NOT NULL,
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
            pwd_hash = bcrypt.hash(pwd)
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
    conn.commit()


def main():
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(DDL)
        seed(conn)
    print(f"Base créée: {DB_PATH.resolve()}")


if __name__ == "__main__":
    main()
