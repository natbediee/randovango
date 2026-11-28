import os
import sys
import tempfile
from pathlib import Path

# Les tests écrivent leurs logs dans un dossier temporaire, jamais dans logs/ :
# sinon leurs fiches inventées (ex : un faux "DOUBLON" #12/#11) se mêleraient
# aux vrais logs des scripts. À définir avant tout import d'un module du backend,
# car le dossier est lu à la création du logger (utils/logger_util.py).
os.environ["RANDOVANGO_LOG_DIR"] = tempfile.mkdtemp(prefix="randovango-test-logs-")

# L'API refuse de démarrer sans JWT_SECRET (services/authentification.py, carte #105). Les tests,
# et la CI qui n'a pas de .env, reçoivent un secret de test, lui aussi posé avant tout import.
os.environ.setdefault("JWT_SECRET", "secret-de-test-uniquement-0123456789abcdef")

# main.py crée les bases au démarrage quand ENV vaut « dev » (sa valeur par défaut) : les tests qui
# chargent l'application entière (tests/functional/test_api_access.py) ne doivent jamais le faire.
os.environ.setdefault("ENV", "test")

ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def llm_calls(monkeypatch):
    """
    Aucun test n'écrit dans llm_calls : chaque mesure d'appel d'agent est gardée dans
    cette liste, que les tests peuvent relire. La vraie écriture est testée à part
    (tests/unit/agents/test_llm_calls.py).
    """
    from agents import llm_service

    recorded = []
    monkeypatch.setattr(llm_service, "record_call", recorded.append)
    return recorded


@pytest.fixture(autouse=True)
def rate_limit_counters():
    """
    Chaque test part de compteurs de débit à zéro (api/rate_limit.py, carte #21) : sinon les plans
    créés par un test compteraient pour le suivant, et le plafond d'un plan par jour le bloquerait.
    """
    from api.rate_limit import limiter

    limiter.reset()


@pytest.fixture(autouse=True)
def no_postcode_api(monkeypatch):
    """
    Aucun test n'interroge geo.api.gouv.fr pour les communes d'un code postal (geo_utils.communes_of_postcode,
    issue #184) : sans réponse, une adresse reste telle quelle. Les tests de la conversion remettent la vraie fonction
    et remplacent l'API eux-mêmes (tests/unit/utils/test_address_with_commune.py).
    """
    from utils import geo_utils

    monkeypatch.setattr(geo_utils, "communes_of_postcode", lambda postcode: [])
    monkeypatch.setattr(geo_utils, "LOCALITY_COMMUNES", {})


@pytest.fixture(autouse=True)
def exchange_rates(monkeypatch):
    """
    Aucun test ne lit le site de la BCE ni la table exchange_rates (#275) : le taux est toujours 1,20 $ pour un euro, du
    jour demandé et déjà lu aujourd'hui. Ce taux compense exactement la TVA de 20 % : un dollar fait un euro TTC.
    Les tests du taux lui-même (tests/unit/services/test_exchange_rate_service.py) posent leurs propres valeurs.
    """
    from datetime import datetime

    from services import exchange_rate_store

    monkeypatch.setattr(exchange_rate_store, "last_fetch", lambda: datetime.now())
    monkeypatch.setattr(exchange_rate_store, "rate_on_or_before", lambda day: {"rate_date": day, "usd_per_eur": 1.20})
    monkeypatch.setattr(exchange_rate_store, "oldest_rate", lambda: None)


@pytest.fixture(autouse=True)
def no_write_lock(monkeypatch):
    """
    Aucun test ne demande le verrou d'écriture commun à MySQL (MySQLUtils.write_lock, issue #361) : les tests qui
    remplacent la base par une fausse connexion ne savent pas répondre à GET_LOCK. Le bloc s'exécute tout de suite.
    Les tests du verrou remettent la vraie fonction (tests/unit/utils/test_db_utils.py, REAL_WRITE_LOCK).
    """
    from contextlib import nullcontext

    from utils.db_utils import MySQLUtils

    monkeypatch.setattr(MySQLUtils, "write_lock", staticmethod(lambda label: nullcontext()))


@pytest.fixture
def deadlocked_base(monkeypatch):
    """
    Une fausse base MySQL dont le premier commit est annulé pour interblocage (erreur 1213), et le second accepté :
    pour vérifier qu'une écriture des étapes de la file est refaite (issue #361). Rend la fausse connexion ; ses
    commits se comptent avec connection.commit.call_count. Les attentes entre deux essais ne durent pas.
    """
    from unittest.mock import MagicMock

    import mysql.connector

    from utils import db_utils

    connection = MagicMock()
    connection.commit.side_effect = [mysql.connector.errors.InternalError(msg="Deadlock found", errno=1213), None]
    monkeypatch.setattr(db_utils.MySQLUtils, "connect", staticmethod(lambda: connection))
    monkeypatch.setattr(db_utils.MySQLUtils, "disconnect", staticmethod(lambda cnx: None))
    monkeypatch.setattr(db_utils.time, "sleep", lambda seconds: None)
    return connection
