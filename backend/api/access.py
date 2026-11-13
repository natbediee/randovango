"""
Le niveau d'accès de chaque route, lu dans ses dépendances (carte #106).

Une route est protégée par les dépendances qu'elle déclare (api/dependencies.py). Plutôt que de
recopier ces règles à la main dans la documentation, on les relit dans les routes elles-mêmes :
la doc OpenAPI (/docs) et la grille de tests (tests/functional/test_api_access.py) disent donc
toujours ce que fait vraiment le code.
"""
from fastapi.routing import APIRoute

from api.dependencies import get_current_traveller, get_current_user, require_admin, require_plan_owner

# Du plus ouvert au plus fermé : ce qu'il faut pour passer, et les refus possibles.
PUBLIC = "public"
TRAVELLER = "voyageur"
PLAN_OWNER = "propriétaire du plan"
ACCOUNT = "compte"
ADMIN = "admin"

LEVEL_TEXT = {
    PUBLIC: "ouvert à tous, sans jeton.",
    TRAVELLER: "jeton exigé, de compte ou d'invité (cookie access_token).",
    PLAN_OWNER: "jeton exigé, et le plan doit appartenir au voyageur du jeton.",
    ACCOUNT: "réservé aux comptes connectés ; un invité est refusé.",
    ADMIN: "réservé aux comptes qui ont le rôle admin, relu en base à chaque appel.",
}

UNAUTHORIZED = {401: {"description": "Jeton absent, faux ou expiré."}}
FORBIDDEN_ACCOUNT = {403: {"description": "Invité sur une route de compte, ou compte sans le rôle demandé."}}
FORBIDDEN_PLAN = {403: {"description": "Le plan appartient à un autre voyageur."}}
PLAN_NOT_FOUND = {404: {"description": "Ce plan n'existe pas."}}

LEVEL_RESPONSES = {
    PUBLIC: {},
    TRAVELLER: UNAUTHORIZED,
    PLAN_OWNER: UNAUTHORIZED | FORBIDDEN_PLAN | PLAN_NOT_FOUND,
    ACCOUNT: UNAUTHORIZED | FORBIDDEN_ACCOUNT,
    ADMIN: UNAUTHORIZED | FORBIDDEN_ACCOUNT,
}


def dependency_calls(dependant) -> set:
    """Toutes les fonctions de dépendance d'une route, y compris celles des dépendances elles-mêmes."""
    calls = set()
    for dependency in dependant.dependencies:
        calls.add(dependency.call)
        calls |= dependency_calls(dependency)
    return calls


def access_level(route: APIRoute) -> str:
    """Le niveau d'accès d'une route : le plus strict des contrôles qu'elle déclare."""
    calls = dependency_calls(route.dependant)
    if require_admin in calls:
        return ADMIN
    if get_current_user in calls:
        return ACCOUNT
    if require_plan_owner in calls:
        return PLAN_OWNER
    if get_current_traveller in calls:
        return TRAVELLER
    return PUBLIC


def document_access(app) -> None:
    """
    Écrit dans la doc OpenAPI de chaque route son niveau d'accès et ses refus possibles (401, 403, 404).
    À appeler après avoir branché tous les routers : FastAPI construit la doc au premier appel de /docs.
    """
    for route in app.routes:
        if isinstance(route, APIRoute):
            level = access_level(route)
            route.description = f"**Accès ({level}) :** {LEVEL_TEXT[level]}\n\n{route.description}"
            route.responses = {**LEVEL_RESPONSES[level], **route.responses}
