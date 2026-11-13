"""
Le contrôle d'accès commun aux routes (api/dependencies.py, carte #103) : qui appelle, d'après
le jeton du cookie, et a-t-il le droit d'entrer ? Les jetons et leur signature sont les vrais.
"""
from datetime import timedelta

import pytest
from fastapi import HTTPException

from api import dependencies
from services.authentification import create_access_token, create_guest_token

ACCOUNT = {"user_id": 7, "username": "camille"}


def status_of(call) -> int:
    """Le code HTTP de l'erreur levée par la dépendance."""
    with pytest.raises(HTTPException) as error:
        call()
    return error.value.status_code


def test_account_token_gives_the_account():
    """Le jeton posé à la connexion donne le compte : son user_id et son nom."""
    traveller = dependencies.get_current_traveller(create_access_token(ACCOUNT))
    assert traveller == {"user_id": 7, "username": "camille", "guest_id": None}


def test_guest_token_gives_a_guest_without_account():
    """Le jeton invité donne un voyageur reconnu par son identifiant invité, sans compte."""
    traveller = dependencies.get_current_traveller(create_guest_token())
    assert traveller["user_id"] is None
    assert len(traveller["guest_id"]) == 36


def test_each_guest_token_is_a_new_guest():
    """Deux jetons invités ne désignent jamais le même voyageur : l'identifiant est tiré au hasard par le serveur."""
    first = dependencies.get_current_traveller(create_guest_token())
    second = dependencies.get_current_traveller(create_guest_token())
    assert first["guest_id"] != second["guest_id"]


@pytest.mark.parametrize("token", [None, "pas-un-jeton"])
def test_missing_or_fake_token_is_refused(token):
    """Sans cookie, ou avec un jeton qui n'est pas signé par l'API, la réponse est 401."""
    assert status_of(lambda: dependencies.get_current_traveller(token)) == 401


def test_expired_token_is_refused():
    """Un jeton expiré est refusé avec 401, même si sa signature est bonne."""
    expired = create_access_token(ACCOUNT, timedelta(minutes=-1))
    assert status_of(lambda: dependencies.get_current_traveller(expired)) == 401


def test_token_without_identity_is_refused():
    """Un jeton bien signé mais sans compte ni identifiant invité est refusé avec 401."""
    empty = create_access_token({"roles": ["admin"]})
    assert status_of(lambda: dependencies.get_current_traveller(empty)) == 401


def test_guest_cannot_use_account_routes():
    """Un invité est refusé (403) sur les routes des comptes, comme l'envoi de tracés GPX."""
    guest = dependencies.get_current_traveller(create_guest_token())
    assert status_of(lambda: dependencies.get_current_user(guest)) == 403


def test_account_passes_account_routes():
    """Un compte connecté passe les routes des comptes."""
    account = dependencies.get_current_traveller(create_access_token(ACCOUNT))
    assert dependencies.get_current_user(account)["username"] == "camille"


def test_admin_role_is_read_from_the_database(monkeypatch):
    """Le rôle admin est relu en base à chaque appel : un compte sans ce rôle reçoit 403, un admin passe."""
    account = {"user_id": 7, "username": "camille", "guest_id": None}
    monkeypatch.setattr(dependencies, "get_roles_for_user", lambda user_id: {"contributor"})
    assert status_of(lambda: dependencies.require_admin(account)) == 403
    monkeypatch.setattr(dependencies, "get_roles_for_user", lambda user_id: {"admin"})
    assert dependencies.require_admin(account) == account
