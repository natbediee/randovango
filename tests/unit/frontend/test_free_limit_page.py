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


def test_free_limit_page_offers_to_resume_the_trip_of_the_day():
    """La page propose de reprendre le voyage du jour, sinon dit que ce navigateur ne le garde plus (issue #262)."""
    page = load_front().test_client().get("/limite-gratuite").get_data(as_text=True)
    assert "Reprendre mon voyage du jour" in page
    assert "Ce navigateur ne garde plus ton voyage du jour." in page
    assert page.index("js/trip_resume.js") < page.index("js/free_limit.js")


def too_long_trip_page():
    """Le HTML de la page de l'offre pour un séjour de plus de 7 jours (issue #263)."""
    return load_front().test_client().get("/limite-gratuite?reason=duration").get_data(as_text=True)


def test_too_long_trip_is_explained():
    """Un voyageur qui demande plus de 7 jours lit que l'offre gratuite s'arrête à 7 jours et que l'offre payante viendra."""
    page = too_long_trip_page()
    assert "Ton séjour dépasse les 7 jours de l'offre gratuite" in page
    assert "Les séjours plus longs viendront avec l'offre payante." in page
    assert "Ton voyage gratuit du jour est déjà composé" not in page


def test_too_long_trip_leads_back_to_the_duration():
    """Pour un séjour trop long, la carte « Gratuit » ramène au choix de la durée : il n'y a pas de voyage à reprendre."""
    page = too_long_trip_page()
    assert "Revenir au choix de la durée</a>" in page
    assert 'href="/duration"' in page
    assert "Reprendre mon voyage du jour" not in page


def test_too_long_trip_keeps_both_offers():
    """La page d'un séjour trop long garde les deux offres, dont les séjours de plus de 7 jours annoncés « Bientôt »."""
    page = too_long_trip_page()
    assert "Jusqu'à 7 jours de séjour" in page
    assert "Des séjours de plus de 7 jours" in page
    assert "disabled>Bientôt disponible" in page
