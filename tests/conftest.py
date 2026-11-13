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
