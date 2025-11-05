import sqlite3
import logging
import os
from jose import jwt, JWTError
from datetime import datetime, timedelta
from fastapi import HTTPException
from dotenv import load_dotenv

from pathlib import Path

# ------ Config --------
DB_PATH = Path("/usr/src/storage/rando_users.sqlite")

load_dotenv()

# --- JWT Config ---
SECRET_KEY = os.getenv("JWT_SECRET", "dev-secret")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60


# --- DB ---
def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


# --- Util DB ---
def get_user_by_username(username) -> tuple | None:
    with connect() as c:
        cur = c.execute("SELECT * FROM users WHERE username=?", (username,))
        return cur.fetchone()


def get_user_by_id(uid):
    with connect() as c:
        cur = c.execute("SELECT * FROM users WHERE id=?", (uid,))
        return cur.fetchone()


def get_roles_for_user(uid):
    sql = """
    SELECT r.name FROM roles r
    JOIN user_role ur ON ur.role_id = r.id
    WHERE ur.user_id = ?
    """
    with connect() as c:
        return {row[0] for row in c.execute(sql, (uid,))}


def insert_auth_log(user_id, username, action, route, status_code, token=None, filename=None):
    logging.info(f"insert_auth_log: user_id={user_id}, username={username}, action={action}, route={route}, status_code={status_code}, token={token}, filename={filename}")
    with connect() as c:
        c.execute(
            """INSERT INTO auth_log(user_id, username, token, action, route, status_code, ip_address, access_type, filename, expires_at)
                     VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (user_id, username, token, action, route, status_code, None, None, filename, None),
        )
        c.commit()


# --- JWT Token Generation ---
def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    from datetime import timezone
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

# --- JWT Token Verification ---
def verify_access_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
