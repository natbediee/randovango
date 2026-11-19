"""
Plafond des essais de connexion (api/rate_limit.py, issue #264) : au-delà de 5 échecs pour un compte,
ou de 20 pour une adresse, en 15 minutes, POST /api/auth/login répond 429 avec un message clair.

Les comptes et le journal des connexions sont remplacés ; le mot de passe, slowapi et ses compteurs
sont les vrais (remis à zéro avant chaque test par conftest.py).
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from passlib.hash import bcrypt

from api import rate_limit
from api.routers import auth

PASSWORD = "bon-mot-de-passe"
# Une ligne de la table users : id, username, password_hash, is_active.
ACCOUNT = (7, "camille", bcrypt.hash(PASSWORD), 1)
ADDRESS = "203.0.113.5"


@pytest.fixture
def journal(monkeypatch):
    """L'API de connexion seule, avec un compte admin « camille » ; chaque ligne écrite dans auth_log est notée ici."""
    lines = []
    monkeypatch.setattr(auth, "get_user_by_username", lambda username: ACCOUNT if username == "camille" else None)
    monkeypatch.setattr(auth, "get_roles_for_user", lambda user_id: {"admin"})
    monkeypatch.setattr(auth, "insert_auth_log", lambda *args, **kwargs: lines.append(args))
    return lines


@pytest.fixture
def client(journal):
    app = FastAPI()
    app.include_router(auth.router, prefix="/api/auth")
    return TestClient(app)


def login(client, username="camille", password="faux", address=ADDRESS):
    """Un essai de connexion, depuis l'adresse transmise par nginx dans X-Real-IP."""
    return client.post("/api/auth/login", json={"username": username, "password": password},
                       headers={"X-Real-IP": address})


def test_sixth_failure_on_an_account_is_refused(client):
    """Après 5 mots de passe faux sur un compte admin, le sixième essai reçoit 429 au lieu de 401."""
    statuses = [login(client).status_code for _ in range(6)]
    assert statuses == [401] * 5 + [429]


def test_refusal_says_why_and_when(client):
    """Le refus dit en français qu'il y a eu trop d'essais manqués et quand réessayer, dans detail comme les autres plafonds."""
    for _ in range(5):
        login(client)
    assert login(client).json() == {"detail": rate_limit.LOGIN_FAILURES_MESSAGE}
    assert "15 minutes" in rate_limit.LOGIN_FAILURES_MESSAGE


def test_blocked_account_refuses_even_the_right_password(client):
    """Une fois le compte au plafond, même le bon mot de passe est refusé : sinon le script finirait par le trouver."""
    for _ in range(5):
        login(client)
    response = login(client, password=PASSWORD)
    assert response.status_code == 429
    assert "set-cookie" not in response.headers


def test_account_is_counted_from_every_address(client):
    """Le compteur du compte vaut quelle que soit l'adresse : changer de machine ne donne pas 5 essais de plus."""
    for number in range(5):
        login(client, address=f"203.0.113.{number}")
    assert login(client, address="198.51.100.1").status_code == 429


def test_account_name_is_counted_without_case(client):
    """Écrire « Camille » au lieu de « camille » ne remet pas le compteur du compte à zéro."""
    for _ in range(5):
        login(client)
    assert login(client, username="CAMILLE").status_code == 429


def test_address_is_capped_across_account_names(client):
    """Une adresse qui essaie 20 noms de compte différents sans succès reçoit 429 au vingt et unième."""
    statuses = [login(client, username=f"inconnu-{number}").status_code for number in range(21)]
    assert statuses == [401] * 20 + [429]
    assert login(client, username="autre", address="198.51.100.1").status_code == 401


def test_successful_logins_are_not_counted(client):
    """Les connexions réussies ne comptent pas : un contributeur qui se connecte souvent n'est jamais bloqué."""
    statuses = [login(client, password=PASSWORD).status_code for _ in range(10)]
    assert statuses == [200] * 10


def test_refusal_is_written_in_the_journal(client, journal):
    """Un essai refusé par le plafond est noté dans auth_log, avec le compte, l'action login_rate_limited et le code 429."""
    for _ in range(6):
        login(client)
    assert journal[-1] == (7, "camille", "login_rate_limited", "/auth/login", 429)
    assert [line[2] for line in journal] == ["failed_login"] * 5 + ["login_rate_limited"]


def test_login_cap_can_be_switched_off_for_development(client, monkeypatch):
    """Avec les plafonds coupés (RATE_LIMIT_ENABLED=0), les essais manqués restent en 401 sans limite."""
    monkeypatch.setattr(rate_limit.limiter, "enabled", False)
    statuses = [login(client).status_code for _ in range(8)]
    assert statuses == [401] * 8
