"""
La page « voyage gratuit du jour déjà composé » (frontend/templates/pages/free_limit.html, carte #21),
rendue par le vrai front Flask.
"""
import importlib.util
import sys
from pathlib import Path

FRONTEND_APP = Path(__file__).resolve().parents[3] / "frontend" / "app.py"


def load_front():
    """Le front Flask, chargé depuis son fichier (son nom, app.py, est trop courant pour un import)."""
    spec = importlib.util.spec_from_file_location("frontend_app", FRONTEND_APP)
    module = importlib.util.module_from_spec(spec)
    # Flask cherche ses gabarits à côté du module qu'il trouve dans sys.modules : il doit y être.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.app


def test_free_limit_page_explains_the_limit():
    """La page dit au voyageur que son voyage gratuit du jour est composé, et qu'il peut revenir demain."""
    page = load_front().test_client().get("/limite-gratuite").get_data(as_text=True)
    assert "Ton voyage gratuit du jour est déjà composé" in page
    assert "Reviens demain" in page


def test_unlimited_offer_is_not_sold_yet():
    """L'offre illimitée est annoncée, mais son bouton reste désactivé : elle n'existe pas encore."""
    page = load_front().test_client().get("/limite-gratuite").get_data(as_text=True)
    assert "Bientôt disponible</button>" in page
    assert "disabled>Bientôt disponible" in page
