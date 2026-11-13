import sqlite3
import logging
import os
import uuid
from jose import jwt, JWTError
from datetime import datetime, timedelta
from fastapi import HTTPException

from pathlib import Path

from utils.service_utils import ServiceUtil

# ------ Config --------
DB_PATH = Path("/usr/src/storage/rando_users.sqlite")

# Le .env est chargé ici, et pas seulement dans main.py : main.py importe les routers (donc ce
# fichier) avant d'appeler load_dotenv, et le secret doit être lu dès l'import.
ServiceUtil.load_env()

# --- JWT Config ---
# HS256 signe le jeton avec une clé de 256 bits : une clé plus courte se devine plus vite (RFC 7518, § 3.2).
JWT_SECRET_MIN_LENGTH = 32


def load_jwt_secret() -> str:
    """
    Lit le secret qui signe les jetons de connexion (JWT_SECRET), ou refuse de continuer.

    Pourquoi refuser : avec un secret par défaut écrit dans le code (avant : "dev-secret"), toute
    personne qui lit le dépôt Git peut fabriquer un jeton admin valide. Sans variable, ou avec un
    secret trop court, l'API ne démarre donc pas, et le message dit quoi corriger.
    """
    secret = os.getenv("JWT_SECRET", "")
    if not secret:
        raise RuntimeError("JWT_SECRET manquant dans le .env : l'API ne peut pas signer les jetons de connexion.")
    if len(secret) < JWT_SECRET_MIN_LENGTH:
        raise RuntimeError(f"JWT_SECRET trop court : {JWT_SECRET_MIN_LENGTH} caractères au moins.")
    return secret


# Lu une seule fois, à l'import : une erreur ici arrête le démarrage de l'API, pas une requête.
SECRET_KEY = load_jwt_secret()
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60
# Un voyageur sans compte garde son jeton invité 30 jours : il revient à son voyage d'un jour à l'autre.
GUEST_TOKEN_EXPIRE_DAYS = 30


# --- Cookie de connexion (carte #24) ---
# Le jeton voyage dans un cookie, et plus dans le localStorage : un script injecté dans une page
# (faille XSS) lit tout le localStorage, mais ne peut pas lire un cookie httpOnly.
AUTH_COOKIE_NAME = "access_token"
# Le cookie n'est envoyé qu'aux routes de l'API, pas aux pages du front, qui n'en ont pas besoin.
AUTH_COOKIE_PATH = "/api"


def cookie_is_secure() -> bool:
    """
    Le cookie part-il seulement en HTTPS ? Oui par défaut (préprod, prod).
    COOKIE_SECURE=0 le permet en HTTP, pour le poste de développement : Safari refuse
    un cookie « Secure » sur http://localhost, même si Chrome et Firefox l'acceptent.
    """
    return os.getenv("COOKIE_SECURE", "1") != "0"


def set_auth_cookie(response, token: str, expires_delta: timedelta) -> None:
    """
    Pose le jeton de connexion dans le cookie de la réponse.

    - httponly : le JavaScript de la page ne peut ni le lire ni le modifier (protection contre le vol par XSS) ;
      le navigateur le joint tout seul aux appels de l'API.
    - samesite="lax" : le navigateur ne le joint pas aux POST, PUT ou DELETE venus d'un autre site. C'est la
      protection contre la falsification de requête (CSRF) : une page piégée ne peut pas agir au nom du voyageur.
      Elle suppose qu'aucune route GET ne modifie de données.
    - max_age : le cookie disparaît à l'expiration du jeton (expires_delta), pas avant, pas après.
    """
    response.set_cookie(
        key=AUTH_COOKIE_NAME,
        value=token,
        max_age=int(expires_delta.total_seconds()),
        path=AUTH_COOKIE_PATH,
        httponly=True,
        samesite="lax",
        secure=cookie_is_secure(),
    )


def clear_auth_cookie(response) -> None:
    """Efface le cookie de connexion. Le JavaScript ne peut pas le faire lui-même : il ne le voit pas."""
    response.delete_cookie(
        key=AUTH_COOKIE_NAME,
        path=AUTH_COOKIE_PATH,
        httponly=True,
        samesite="lax",
        secure=cookie_is_secure(),
    )


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


def insert_auth_log(user_id, username, action, route, status_code, filename=None):
    """
    Note une connexion ou une action sensible dans auth_log (qui, quoi, quand, avec quel résultat).

    Le jeton n'y est jamais écrit (carte #61) : un jeton lu dans la base ou dans les journaux se
    rejoue tel quel jusqu'à son expiration, comme un mot de passe. Pour savoir qui a fait quoi,
    user_id et username suffisent ; la colonne token reste vide.
    """
    logging.info(f"insert_auth_log: user_id={user_id}, username={username}, action={action}, route={route}, status_code={status_code}, filename={filename}")
    with connect() as c:
        c.execute(
            """INSERT INTO auth_log(user_id, username, action, route, status_code, ip_address, access_type, filename, expires_at)
                     VALUES (?,?,?,?,?,?,?,?,?)""",
            (user_id, username, action, route, status_code, None, None, filename, None),
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


def create_guest_token() -> str:
    """
    Jeton d'un voyageur sans compte (carte #103). Il porte un identifiant invité tiré au hasard par
    le serveur, jamais choisi par le navigateur : personne ne peut se déclarer l'invité d'un autre.
    Il n'a ni user_id ni rôle : il ouvre les routes du voyage, jamais celles des comptes.
    """
    return create_access_token({"guest_id": str(uuid.uuid4())}, timedelta(days=GUEST_TOKEN_EXPIRE_DAYS))

# --- JWT Token Verification ---
def verify_access_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
