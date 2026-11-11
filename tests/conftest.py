import os
import sys
import tempfile
from pathlib import Path

# Les tests écrivent leurs logs dans un dossier temporaire, jamais dans logs/ :
# sinon leurs fiches inventées (ex : un faux "DOUBLON" #12/#11) se mêleraient
# aux vrais logs des scripts. À définir avant tout import d'un module du backend,
# car le dossier est lu à la création du logger (utils/logger_util.py).
os.environ["RANDOVANGO_LOG_DIR"] = tempfile.mkdtemp(prefix="randovango-test-logs-")

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
