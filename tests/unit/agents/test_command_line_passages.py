"""
Un lancement d'agent en ligne de commande (python -m agents.xxx) est un passage : tous ses appels portent le même
identifiant dans llm_calls (issue #276). Au 17 novembre 2026, 189 appels sur 847 n'en avaient aucun.
"""
from pathlib import Path

import pytest

AGENTS = Path(__file__).resolve().parents[3] / "backend" / "agents"
# La chaîne des services pose déjà son passage elle-même, commune par commune (agents/find_services.py, #204).
OWN_PASSAGE = {"find_services.py"}
COMMAND_LINES = sorted(path.name for path in AGENTS.glob("*.py")
                       if "\ndef main(" in path.read_text(encoding="utf-8") and path.name not in OWN_PASSAGE)


def test_every_agent_with_a_command_line_is_found():
    """Les agents lancés en ligne de commande sont bien trouvés : spots, pépites, liens des services, doublons."""
    assert {"harmonize_spots.py", "read_openings.py", "verify_spots.py", "dedupe_spots.py", "discover_places.py",
            "find_pepites.py", "locate_pepites.py", "find_service_links.py"} <= set(COMMAND_LINES)


@pytest.mark.parametrize("name", COMMAND_LINES)
def test_a_command_line_launch_runs_under_its_own_passage(name):
    """Chaque agent lancé en ligne de commande ouvre un passage avant main() : ses appels ne restent plus sans identifiant."""
    source = (AGENTS / name).read_text(encoding="utf-8")
    entry = source.split('if __name__ == "__main__":', 1)[1]
    assert "with mesure_passage(new_passage_id()):\n        main()" in entry
