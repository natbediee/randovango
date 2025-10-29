import sys
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path

from api.routers import step1, step2, step3, step4, result, auth, etl
from utils.logger_util import LoggerUtil

app = FastAPI(
    title="RandoVanGo API",
    description="API du planificateurs",
)

# Configuration CORS pour autoriser les requêtes depuis le frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5000", "http://localhost:8000"],  # Origines autorisées
    allow_credentials=True,
    allow_methods=["*"],  # Toutes les méthodes HTTP
    allow_headers=["*"],  # Tous les headers
)

app.include_router(step1.router, prefix="/api/step1", tags=["Step 1 Cities"])
app.include_router(step2.router, prefix="/api/step2", tags=["Step 2 Hikes"])
app.include_router(step3.router, prefix="/api/step3", tags=["Step 3 Spots"])
app.include_router(step4.router, prefix="/api/step4", tags=["Step 4 Services"])
app.include_router(result.router, prefix="/api/result", tags=["Result Plan"])
app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(etl.router, prefix="/api/etl", tags=["Upload GPX"])


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

init_sqlite_users()
init_mysql_randovango()
