"""
Contrôle d'accès des routes de l'API (carte #103) : qui appelle, et a-t-il le droit d'entrer ?

Ces fonctions sont des dépendances FastAPI : une route les déclare avec Depends(...), et FastAPI
les exécute AVANT le code de la route. Si l'une lève une HTTPException, la route ne s'exécute pas
du tout : aucune lecture, aucun appel d'agent n'a lieu. Elles s'enchaînent de la plus large à la
plus stricte :

    get_current_traveller   tout porteur d'un jeton valide : compte ou invité   (sinon 401)
      └ get_current_user    un compte, pas un invité                            (sinon 403)
          └ require_admin   un compte qui a le rôle admin en base               (sinon 403)
      └ require_plan_owner  le propriétaire du plan demandé, compte ou invité (sinon 404 ou 403)

401 veut dire « je ne sais pas qui tu es » ; 403 « je sais qui tu es, et c'est non ».
"""
from fastapi import Depends, HTTPException
from fastapi.security import APIKeyCookie
from jose import JWTError, jwt

from services.authentification import ALGORITHM, AUTH_COOKIE_NAME, SECRET_KEY, get_roles_for_user
from services.plan_service import get_plan_owner

# Le jeton est lu dans le cookie httpOnly, et nulle part ailleurs (carte #24) : un en-tête
# « Authorization: Bearer » n'est pas accepté. APIKeyCookie décrit aussi ce cookie dans la doc OpenAPI.
# auto_error=False : sans cookie, on répond 401 ci-dessous, et non le 403 par défaut de FastAPI.
auth_cookie = APIKeyCookie(name=AUTH_COOKIE_NAME, auto_error=False)


def identity_from_payload(payload: dict) -> dict:
    """
    L'identité écrite dans un jeton déchiffré : un compte (user_id et username, posés à la
    connexion) ou un invité (guest_id, posé par /api/auth/guest). Tout autre contenu est refusé.
    """
    if payload.get("user_id") is not None and payload.get("username"):
        return {"user_id": payload["user_id"], "username": payload["username"], "guest_id": None}
    if payload.get("guest_id"):
        return {"user_id": None, "username": None, "guest_id": payload["guest_id"]}
    raise HTTPException(status_code=401, detail="Token invalide")


def get_current_traveller(token: str | None = Depends(auth_cookie)) -> dict:
    """
    Qui appelle ? Un compte ou un invité, lu dans le jeton du cookie. 401 si le cookie manque,
    ou si le jeton est faux (signature qui ne correspond pas au secret) ou expiré.
    """
    if token is None:
        raise HTTPException(status_code=401, detail="Token manquant")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Token invalide")
    return identity_from_payload(payload)


def get_current_user(traveller: dict = Depends(get_current_traveller)) -> dict:
    """
    Un compte connecté, pas un invité : les routes des contributeurs et des admins.
    Sans ce contrôle, un jeton invité, que n'importe qui obtient, ouvrirait l'envoi de tracés GPX.
    """
    if traveller["user_id"] is None:
        raise HTTPException(status_code=403, detail="Accès refusé : compte requis")
    return traveller


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """Réservé aux admins. Les rôles sont relus en base : un rôle retiré vaut tout de suite."""
    if "admin" not in get_roles_for_user(user["user_id"]):
        raise HTTPException(status_code=403, detail="Accès refusé : rôle admin requis")
    return user


def is_plan_owner(traveller: dict, owner: dict) -> bool:
    """
    Le plan est-il à ce voyageur ? Un compte possède les plans qui portent son user_id ; un invité,
    ceux qui portent son identifiant invité dans user_token.
    """
    if traveller["user_id"] is not None:
        return owner["user_id"] == traveller["user_id"]
    return owner["user_token"] is not None and owner["user_token"] == traveller["guest_id"]


def require_plan_owner(plan_id: int, traveller: dict = Depends(get_current_traveller)) -> dict:
    """
    Contrôle de propriété du plan (carte #104, OWASP API1 « BOLA ») : les numéros de plan se suivent
    (41, 42, 43…), il suffirait d'en changer un dans l'adresse pour lire ou modifier le voyage d'un
    autre. On compare donc le propriétaire du plan, lu en base, au voyageur du jeton.

    plan_id vient du chemin (/update_plan/{plan_id}) ou de la requête (?plan_id=42) : FastAPI le
    cherche au même endroit que pour la route.
    """
    owner = get_plan_owner(plan_id)
    if owner is None:
        raise HTTPException(status_code=404, detail="Plan introuvable")
    if not is_plan_owner(traveller, owner):
        raise HTTPException(status_code=403, detail="Accès refusé : ce plan appartient à un autre voyageur")
    return traveller
