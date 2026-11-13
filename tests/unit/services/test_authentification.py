"""
Le secret qui signe les jetons de connexion (services/authentification.py, carte #105) :
l'API refuse de démarrer sans lui, ou avec un secret trop court.
"""
import pytest

from services import authentification


def test_missing_secret_stops_the_api(monkeypatch):
    """Sans JWT_SECRET, l'API refuse de démarrer au lieu de signer avec l'ancien « dev-secret » connu de tous."""
    monkeypatch.delenv("JWT_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="JWT_SECRET manquant"):
        authentification.load_jwt_secret()


def test_empty_secret_stops_the_api(monkeypatch):
    """Un JWT_SECRET vide, comme dans .env.example recopié sans le remplir, arrête aussi l'API."""
    monkeypatch.setenv("JWT_SECRET", "")
    with pytest.raises(RuntimeError, match="JWT_SECRET manquant"):
        authentification.load_jwt_secret()


def test_short_secret_stops_the_api(monkeypatch):
    """Un secret de moins de 32 caractères est refusé : il se devine trop vite pour signer en HS256."""
    monkeypatch.setenv("JWT_SECRET", "x" * 31)
    with pytest.raises(RuntimeError, match="trop court"):
        authentification.load_jwt_secret()


def test_long_enough_secret_is_used(monkeypatch):
    """Un secret de 32 caractères ou plus est celui qui signe les jetons."""
    monkeypatch.setenv("JWT_SECRET", "y" * 32)
    assert authentification.load_jwt_secret() == "y" * 32


def test_token_signed_with_the_secret_is_read_back():
    """Un jeton créé à la connexion se relit avec le même secret, et garde son contenu."""
    token = authentification.create_access_token({"user_id": 7, "username": "camille"})
    payload = authentification.verify_access_token(token)
    assert (payload["user_id"], payload["username"]) == (7, "camille")
