"""
La page « Durée » propose de reprendre le voyage en cours (issue #262), rendue par le vrai front Flask,
comme test_free_limit_page.py. Le choix lui-même (afficher l'encadré, oublier le voyage) se fait dans le
navigateur (step_duration.js, trip_resume.js) : il est vérifié à la main dans une vraie page.
"""
# pytest met le dossier de ce test dans le chemin d'import (pas de __init__.py) : on importe le fichier voisin.
from test_free_limit_page import load_front


def duration_page():
    """Le HTML de la page « Durée »."""
    return load_front().test_client().get("/duration").get_data(as_text=True)


def test_duration_page_offers_to_resume_or_start_a_new_trip():
    """La page « Durée » porte les deux choix : reprendre le voyage en cours ou en commencer un nouveau."""
    page = duration_page()
    assert "Ton voyage est en cours" in page
    assert "Reprendre mon voyage" in page
    assert "Commencer un nouveau voyage" in page


def test_resume_box_is_hidden_until_a_trip_is_found():
    """L'encadré est caché au départ : un voyageur sans voyage en cours ne voit que le choix de la durée."""
    assert 'id="tripResume" hidden' in duration_page()


def test_duration_page_loads_the_trip_helpers_before_its_script():
    """trip_resume.js est chargé avant step_duration.js, qui s'en sert dès l'ouverture de la page."""
    page = duration_page()
    assert page.index("js/trip_resume.js") < page.index("js/step_duration.js")
