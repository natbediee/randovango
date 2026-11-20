"""
La doc de l'API (/docs) range les routes de la supervision en une section par ressource (carte #186) : Relectures,
Décisions, Recherche, Services, Passages des agents (issue #204). Avant, les routes étaient toutes dans une seule section « Supervision ».
"""
import pytest

SECTIONS = {
    "Supervision · Relectures": {"/api/supervision/reviews/spots", "/api/supervision/reviews/services",
                                 "/api/supervision/reviews/summary"},
    "Supervision · Décisions": {"/api/supervision/decisions", "/api/supervision/decisions/{decision_id}",
                                "/api/supervision/decisions/{decision_id}/audit"},
    "Supervision · Recherche": {"/api/supervision/search/services", "/api/supervision/search/spots"},
    "Supervision · Services": {"/api/supervision/services/{poi_id}"},
    # Issue #204 : lancer, suivre et reprendre un passage d'une chaîne d'agents.
    "Supervision · Passages des agents": {"/api/supervision/passages", "/api/supervision/passages/{passage_id}",
                                          "/api/supervision/passages/{passage_id}/reprise",
                                          # Issue #211 : le réglage des agents et leur budget.
                                          "/api/supervision/passages/reglage"},
}


@pytest.fixture(scope="module")
def paths():
    """Les routes de la doc OpenAPI de l'application entière, telle que la lance uvicorn (main.py)."""
    import main
    return main.app.openapi()["paths"]


def sections_of(paths: dict) -> dict:
    """{section : les adresses qu'elle montre}, pour les routes de la supervision."""
    sections = {}
    for path, methods in paths.items():
        if path.startswith("/api/supervision"):
            for route in methods.values():
                for tag in route["tags"]:
                    sections.setdefault(tag, set()).add(path)
    return sections


def test_each_supervision_resource_has_its_own_section(paths):
    """Chaque ressource de la supervision a sa section dans /docs, et chaque route est dans la bonne."""
    assert sections_of(paths) == SECTIONS
