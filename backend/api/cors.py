"""
Règles CORS de l'API (carte #25) : quelles pages, sur quels sites, ont le droit d'appeler l'API
depuis le navigateur, avec quelles méthodes et quels en-têtes.

Pourquoi c'est important avec un cookie de connexion : le navigateur joint le cookie aux appels
de la page (credentials: 'include', carte #24). Si l'API autorisait n'importe quelle origine, la
page d'un autre site pourrait appeler l'API au nom du voyageur ET lire la réponse (son plan, la
supervision d'un admin). La liste des origines doit donc être exacte, sans joker.
"""
import os

from fastapi.middleware.cors import CORSMiddleware

# Les origines par défaut : le front servi par nginx sur le poste de développement.
DEFAULT_ORIGINS = "http://localhost,http://127.0.0.1"
# Seules les méthodes qu'utilise l'API. OPTIONS, la question préalable du navigateur, est traitée
# par le middleware lui-même.
ALLOWED_METHODS = ["GET", "POST", "PUT", "DELETE"]
# Le seul en-tête que le front ajoute : Content-Type: application/json. Le jeton passe par le cookie,
# plus par un en-tête Authorization (carte #24).
ALLOWED_HEADERS = ["Content-Type"]


def load_allowed_origins() -> list:
    """
    Les origines autorisées, lues dans ALLOWED_ORIGINS (séparées par des virgules, espaces tolérés).
    « * » est refusé : avec allow_credentials, Starlette renverrait alors l'origine de n'importe quelle
    page, ce qui reviendrait à ouvrir l'API, cookie compris, à tous les sites.
    """
    origins = [origin.strip() for origin in os.getenv("ALLOWED_ORIGINS", DEFAULT_ORIGINS).split(",")]
    origins = [origin for origin in origins if origin]
    if "*" in origins:
        raise RuntimeError("ALLOWED_ORIGINS ne peut pas contenir « * » : le cookie de connexion exige des origines exactes.")
    return origins


def add_cors(app) -> None:
    """Pose les règles CORS sur l'application."""
    app.add_middleware(
        CORSMiddleware,
        allow_origins=load_allowed_origins(),
        allow_credentials=True,  # le navigateur peut joindre le cookie de connexion
        allow_methods=ALLOWED_METHODS,
        allow_headers=ALLOWED_HEADERS,
    )
