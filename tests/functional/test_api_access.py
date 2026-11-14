"""
La grille d'accès de TOUTES les routes de l'API (carte #106) : chaque route y a son niveau, et une
route ajoutée sans y être inscrite fait échouer test_every_route_is_in_the_grid.

L'application entière est la vraie (main.py), avec ses dépendances et ses jetons. Les refus (401, 403)
sont décidés avant le code de la route : ils se testent sans base. Les réponses 200 de chaque route,
qui lisent la base, sont vérifiées dans les tests propres à chaque carte :
    test_plan_access.py (plans), test_pepites_access.py (pépites), test_auth.py (connexion),
    features/supervision_droits.feature (supervision), test_dependencies.py (compte et admin).
"""
import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from api import dependencies
from api.access import ACCOUNT, ADMIN, PLAN_OWNER, PUBLIC, TRAVELLER, access_level
from services.authentification import AUTH_COOKIE_NAME, create_access_token

# La grille : chaque route de l'API et ce qu'il faut pour y entrer.
ACCESS = {
    # Connexion : ouvertes, c'est par elles qu'on obtient un jeton.
    ("POST", "/api/auth/login"): PUBLIC,
    ("POST", "/api/auth/guest"): PUBLIC,
    ("POST", "/api/auth/logout"): PUBLIC,
    # Ce que tout le monde peut consulter : villes, randos, spots, services.
    ("GET", "/api/step1/cities/bounds"): PUBLIC,
    ("GET", "/api/step1/cities"): PUBLIC,
    ("GET", "/api/step1/refresh-meteo/{city_id}"): PUBLIC,
    ("GET", "/api/step2/hikes"): PUBLIC,
    ("GET", "/api/step2/hike/{hike_id}/trace"): PUBLIC,
    # plan_id facultatif : la route n'en lit que la date de départ, pour la date de la nuit, et n'en renvoie rien.
    ("GET", "/api/step3/spots"): PUBLIC,
    ("GET", "/api/step4/poi"): PUBLIC,
    # Le voyage : un jeton, puis le plan doit être à ce voyageur.
    ("POST", "/api/step1/create_plan"): TRAVELLER,
    ("GET", "/api/pepites/trail-tips"): TRAVELLER,
    ("PUT", "/api/step1/update_day_city/{plan_id}"): PLAN_OWNER,
    ("PUT", "/api/step2/update_plan/{plan_id}"): PLAN_OWNER,
    ("PUT", "/api/step3/update_plan/{plan_id}"): PLAN_OWNER,
    ("PUT", "/api/step4/update_plan/{plan_id}"): PLAN_OWNER,
    ("GET", "/api/result/"): PLAN_OWNER,
    ("GET", "/api/result/pdf"): PLAN_OWNER,
    ("GET", "/api/pepites/"): PLAN_OWNER,
    ("GET", "/api/pepites/news"): PLAN_OWNER,
    ("PUT", "/api/pepites/seen/{plan_id}"): PLAN_OWNER,
    ("PUT", "/api/pepites/choose/{plan_id}"): PLAN_OWNER,
    # Les contributeurs.
    ("POST", "/api/etl/upload_gpx"): ACCOUNT,
    # Les admins.
    ("DELETE", "/api/etl/delete_gpx/{filename}"): ADMIN,
    ("POST", "/api/supervision/decisions"): ADMIN,
    ("PUT", "/api/supervision/decisions/{decision_id}"): ADMIN,
    ("DELETE", "/api/supervision/decisions/{decision_id}"): ADMIN,
    ("DELETE", "/api/supervision/openings/{decision_id}"): ADMIN,
    ("POST", "/api/supervision/services/decisions"): ADMIN,
    ("POST", "/api/supervision/services/fiche"): ADMIN,
    ("POST", "/api/supervision/services/audit/{decision_id}"): ADMIN,
    ("DELETE", "/api/supervision/services/decisions/{decision_id}"): ADMIN,
    ("POST", "/api/supervision/edit/services/decisions"): ADMIN,
    ("POST", "/api/supervision/edit/services/fiche"): ADMIN,
    ("DELETE", "/api/supervision/edit/services/decisions/{decision_id}"): ADMIN,
    ("POST", "/api/supervision/edit/spots/decisions"): ADMIN,
    ("PUT", "/api/supervision/edit/spots/decisions/{decision_id}"): ADMIN,
    ("DELETE", "/api/supervision/edit/spots/decisions/{decision_id}"): ADMIN,
    ("POST", "/api/supervision/edit/spots/openings"): ADMIN,
    ("DELETE", "/api/supervision/edit/spots/openings/{decision_id}"): ADMIN,
    ("GET", "/api/supervision/reviews/spots"): ADMIN,
    ("GET", "/api/supervision/reviews/services"): ADMIN,
    ("GET", "/api/supervision/reviews/summary"): ADMIN,
    ("GET", "/api/supervision/search/services"): ADMIN,
    ("GET", "/api/supervision/search/spots"): ADMIN,
    ("GET", "/api/supervision/services/{poi_id}"): ADMIN,
}

# Les paramètres de chemin et de requête des routes, pour les appeler vraiment.
PATH_VALUES = {"{plan_id}": "1", "{city_id}": "1", "{hike_id}": "1", "{filename}": "trace.gpx",
               "{decision_id}": "1", "{poi_id}": "1"}
QUERY = "?plan_id=1&day_number=1&hike_ids=1&city_id=1"


def routes_at(*levels) -> list:
    """Les routes de la grille qui ont l'un de ces niveaux d'accès."""
    return [route for route, level in ACCESS.items() if level in levels]


def concrete(path: str) -> str:
    """L'adresse d'une route avec des valeurs à la place de ses paramètres."""
    for placeholder, value in PATH_VALUES.items():
        path = path.replace(placeholder, value)
    return path + QUERY


@pytest.fixture(scope="module")
def app():
    """L'application entière, telle que la lance uvicorn (main.py)."""
    import main
    return main.app


@pytest.fixture
def client(app):
    return TestClient(app)


def call(client, method: str, path: str, token: str | None = None):
    """Appelle une route, avec le cookie de connexion si un jeton est donné."""
    if token:
        client.cookies.set(AUTH_COOKIE_NAME, token)
    body = {"json": {}} if method in ("POST", "PUT") else {}
    return client.request(method, concrete(path), **body)


def test_every_route_is_in_the_grid(app):
    """Chaque route de l'API est dans la grille, avec le niveau que déclarent vraiment ses dépendances."""
    declared = {(method, route.path): access_level(route)
                for route in app.routes if isinstance(route, APIRoute) for method in route.methods}
    assert declared == ACCESS


@pytest.mark.parametrize("method,path", routes_at(TRAVELLER, PLAN_OWNER, ACCOUNT, ADMIN))
def test_protected_route_refuses_without_token(client, method, path):
    """Sans cookie, toute route protégée répond 401, avant d'exécuter la moindre ligne de la route."""
    assert call(client, method, path).status_code == 401


@pytest.mark.parametrize("method,path", routes_at(TRAVELLER, PLAN_OWNER, ACCOUNT, ADMIN))
def test_protected_route_refuses_a_fake_token(client, method, path):
    """Un jeton qui n'est pas signé par l'API est refusé (401) sur toute route protégée."""
    assert call(client, method, path, "pas-un-jeton").status_code == 401


@pytest.mark.parametrize("method,path", routes_at(ACCOUNT, ADMIN))
def test_guest_refused_on_account_routes(client, method, path):
    """Un invité, même avec un jeton valide, est refusé (403) sur les routes des contributeurs et des admins."""
    assert call(client, method, path, create_access_token({"guest_id": "invite-1"})).status_code == 403


@pytest.mark.parametrize("method,path", routes_at(ADMIN))
def test_account_without_admin_role_refused_on_admin_routes(client, method, path, monkeypatch):
    """Un compte sans le rôle admin en base est refusé (403) sur toutes les routes d'admin."""
    monkeypatch.setattr(dependencies, "get_roles_for_user", lambda user_id: {"contributor"})
    token = create_access_token({"user_id": 7, "username": "camille"})
    assert call(client, method, path, token).status_code == 403


@pytest.mark.parametrize("method,path", routes_at(PLAN_OWNER))
def test_plan_of_another_traveller_is_refused(client, method, path, monkeypatch):
    """Le plan d'un autre voyageur est refusé (403) sur toutes les routes de plan."""
    monkeypatch.setattr(dependencies, "get_plan_owner", lambda plan_id: {"user_id": 0, "user_token": "invite-2"})
    assert call(client, method, path, create_access_token({"guest_id": "invite-1"})).status_code == 403


def test_openapi_documents_each_access_level(client):
    """La doc OpenAPI donne à chaque route protégée son niveau d'accès et sa réponse 401."""
    paths = client.get("/openapi.json").json()["paths"]
    for (method, path), level in ACCESS.items():
        operation = paths[path][method.lower()]
        assert operation["description"].startswith(f"**Accès ({level}) :**")
        if level != PUBLIC:
            assert "401" in operation["responses"]


def test_openapi_describes_the_cookie(client):
    """La doc OpenAPI décrit le cookie access_token comme moyen d'authentification."""
    schemes = client.get("/openapi.json").json()["components"]["securitySchemes"]
    assert {"type": "apiKey", "in": "cookie", "name": AUTH_COOKIE_NAME} in schemes.values()
