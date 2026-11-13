"""
Plafonds de débit des routes qui lancent les recherches de Vany (carte #21, OWASP API4).

Choisir une ville ou un spot met Vany au travail en tâche de fond : ses agents appellent un modèle
de langage, et chaque appel coûte. Sans plafond, un script qui répète ces requêtes viderait le
budget en quelques minutes. slowapi compte les appels de chaque voyageur sur chaque route, et
répond 429 (« trop de demandes ») au-delà du plafond, sans exécuter la route.

Les plafonds sont calculés sur un séjour de 7 jours, la plus longue durée proposée : un vrai
voyageur ne les atteint pas. Les compteurs sont en mémoire, remis à zéro au redémarrage de l'API,
ce qui suffit pour un seul serveur.
"""
import os

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded

from api.dependencies import get_current_traveller
from services.authentification import AUTH_COOKIE_NAME

# Un voyage se crée une fois, parfois deux si on recommence. Deux plafonds à la fois (« ; ») :
# 3 dans l'heure, et 5 dans la journée.
CREATE_PLAN_LIMIT = "3/hour;5/day"
# Une ville par jour du séjour (7 au plus), plus quelques changements d'avis.
DAY_CITY_LIMIT = "15/hour"
# Le spot du jour se choisit en quelques clics : environ 3 par jour sur 7 jours.
DAY_SPOT_LIMIT = "30/hour"
# Un jeton invité neuf donne un compteur neuf : sans ce plafond, il suffirait d'en demander un autre
# pour contourner les trois précédents. Compté par adresse IP : 10 nouveaux visiteurs par heure
# derrière un même wifi de camping partagé, avant qu'un onzième soit refusé.
GUEST_TOKEN_LIMIT = "10/hour"


def client_ip(request: Request) -> str:
    """
    L'adresse IP du visiteur. Derrière nginx, l'API ne voit que l'adresse de nginx : nginx transmet
    la vraie dans l'en-tête X-Real-IP (nginx/randovango.conf). Cet en-tête n'est digne de confiance
    que si l'API n'est joignable QUE par nginx ; sinon, un visiteur pourrait l'écrire lui-même.
    """
    return request.headers.get("x-real-ip") or request.client.host


def traveller_key(request: Request) -> str:
    """
    À qui compter l'appel : le voyageur du cookie (compte ou invité), sinon l'adresse IP.
    Compter par voyageur évite qu'un même wifi, partagé par plusieurs voyageurs, ne les bloque ensemble.
    """
    try:
        traveller = get_current_traveller(request.cookies.get(AUTH_COOKIE_NAME))
    except HTTPException:
        return f"ip:{client_ip(request)}"
    if traveller["user_id"] is not None:
        return f"user:{traveller['user_id']}"
    return f"guest:{traveller['guest_id']}"


def rate_limit_enabled() -> bool:
    """
    Les plafonds sont-ils actifs ? Oui par défaut (préprod, prod). RATE_LIMIT_ENABLED=0 les coupe sur
    le poste de développement, où l'on compose beaucoup de voyages pour tester : sans cela, l'adresse
    de la développeuse serait bloquée. Lu une fois, au démarrage de l'API.
    """
    return os.getenv("RATE_LIMIT_ENABLED", "1") != "0"


limiter = Limiter(key_func=traveller_key, enabled=rate_limit_enabled())


def too_many_requests(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """La réponse 429 : un message que le front affiche tel quel au voyageur."""
    return JSONResponse(
        status_code=429,
        content={"detail": "Tu vas un peu vite : trop de demandes en peu de temps. Réessaie dans un moment."},
    )


def add_rate_limit(app) -> None:
    """Branche les plafonds sur l'application : slowapi lit le limiteur dans app.state."""
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, too_many_requests)
