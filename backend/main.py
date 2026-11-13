import sys
import os
from fastapi import FastAPI
from pathlib import Path
from dotenv import load_dotenv

from api.access import document_access
from api.cors import add_cors
from api.rate_limit import add_rate_limit
from api.routers import step1, step2, step3, step4, result, auth, etl, pepites, supervision, supervision_bilan
from utils.logger_util import LoggerUtil

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

# Description affichée en tête de /docs : comment on s'authentifie, et qui a le droit de quoi.
API_DESCRIPTION = """
API du planificateur de voyages en van RandoVanGo.

## Authentification

Le jeton (JWT signé par l'API) est posé dans un **cookie httpOnly `access_token`**, jamais dans le JSON
ni dans un en-tête : le JavaScript des pages ne peut pas le lire.

- **Compte** (contributeur, admin) : `POST /api/auth/login` pose un jeton valable 60 minutes.
- **Voyageur sans compte** : `POST /api/auth/guest` pose un jeton invité valable 30 jours.
- **Déconnexion** : `POST /api/auth/logout` efface le cookie.

Depuis /docs, se connecter avec `/api/auth/login` suffit : le navigateur garde le cookie et le joint aux appels suivants.

## Autorisation

Chaque route affiche son niveau d'accès, lu dans ses dépendances (`api/access.py`) :

| Niveau | Il faut | Sinon |
| --- | --- | --- |
| public | rien | |
| voyageur | un jeton, de compte ou d'invité | 401 |
| propriétaire du plan | un jeton, et le plan doit être à ce voyageur | 401, 404, 403 |
| compte | un jeton de compte (pas d'invité) | 401, 403 |
| admin | un compte qui a le rôle admin, relu en base | 401, 403 |

401 : « je ne sais pas qui tu es » (jeton absent, faux ou expiré). 403 : « je sais qui tu es, et c'est non ».

## Plafonds de débit

Les routes qui lancent les recherches de Vany sont plafonnées par voyageur, et répondent **429** au-delà :
création du plan (1 par jour), ville du jour (15 par heure), spot du jour (30 par heure), jeton invité
(10 par heure et par adresse IP).

## CORS

Seules les origines de `ALLOWED_ORIGINS` peuvent appeler l'API avec le cookie (jamais `*`), avec les
méthodes GET, POST, PUT, DELETE et l'en-tête Content-Type.
"""

app = FastAPI(
    title="RandoVanGo API",
    description=API_DESCRIPTION,
)

# Règles CORS : origines exactes (ALLOWED_ORIGINS), méthodes et en-têtes utilisés seulement (api/cors.py).
add_cors(app)
# Plafonds de débit des routes qui lancent les recherches de Vany (api/rate_limit.py).
add_rate_limit(app)

app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(step1.router, prefix="/api/step1", tags=["Step 1 Cities"])
app.include_router(step2.router, prefix="/api/step2", tags=["Step 2 Hikes"])
app.include_router(step3.router, prefix="/api/step3", tags=["Step 3 Spots"])
app.include_router(step4.router, prefix="/api/step4", tags=["Step 4 Services"])
app.include_router(result.router, prefix="/api/result", tags=["Result Plan"])
app.include_router(pepites.router, prefix="/api/pepites", tags=["Pépites de Vany"])
app.include_router(etl.router, prefix="/api/etl", tags=["GPX Files"])
app.include_router(supervision.router, prefix="/api/supervision", tags=["Supervision"])
app.include_router(supervision_bilan.router, prefix="/api/supervision", tags=["Supervision"])

# Le niveau d'accès de chaque route, écrit dans la doc OpenAPI (api/access.py) : après tous les routers.
document_access(app)


# Logger principal pour le backend
logger = LoggerUtil.get_logger("startup")
logger.info("[TEST] Logger 'startup' initialisé et opérationnel.")

def init_sqlite_users():
    db_path = Path(__file__).resolve().parents[1] / "storage" / "rando_users.sqlite"
    if not db_path.exists():
        logger.info("[INIT] Création de la base utilisateurs SQLite...")
        db_init_script = Path(__file__).parent / "db_init" / "db_users.py"
        os.system(f"{sys.executable} {db_init_script}")
    else:
        logger.info(f"[INIT] Base utilisateurs déjà présente: {db_path}")


def init_mysql_randovango():
    # Vérifie si la base MySQL existe déjà via un flag fichier, sinon lance le script d'init
    flag_path = Path(__file__).resolve().parents[1] / "storage" / ".randovango_db_initialized"
    if not flag_path.exists():
        logger.info("[INIT] Création/init de la base MySQL randovango...")
        db_init_script = Path(__file__).parent / "db_init" / "db_randovango.py"
        exit_code = os.system(f"{sys.executable} {db_init_script}")
        if exit_code == 0:
            flag_path.touch()
            logger.info(f"[INIT] Base MySQL randovango initialisée, flag créé: {flag_path}")
        else:
            logger.error("[ERREUR] L'initialisation de la base MySQL randovango a échoué.")
    else:
        logger.info(f"[INIT] Base MySQL randovango déjà initialisée (flag: {flag_path})")

# Auto-init/seed (comptes par défaut, création de schéma) : uniquement en dev.
# En prod (AWS), les bases sont peuplées une fois pour toutes via restauration de dump,
# pas par le code applicatif à chaque démarrage.
if os.getenv("ENV", "dev") == "dev":
    init_sqlite_users()
    init_mysql_randovango()
else:
    logger.info("[INIT] ENV != dev : auto-init des bases désactivée.")
