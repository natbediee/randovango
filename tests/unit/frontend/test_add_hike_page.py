"""
La page d'ajout d'une randonnée (frontend/templates/pages/add_hike.html) ne montre que ce qui est vraiment envoyé
à l'API : le fichier GPX (issue #265). Page rendue par le vrai front Flask, comme test_free_limit_page.py ;
l'envoi lui-même est vérifié à la main dans une vraie page.
"""
# pytest met le dossier de ce test dans le chemin d'import (pas de __init__.py) : on importe le fichier voisin.
from test_free_limit_page import load_front


def add_hike_page():
    """Le HTML de la page d'ajout d'une randonnée."""
    return load_front().test_client().get("/contributor/add-hike").get_data(as_text=True)


def test_add_hike_page_asks_only_for_the_gpx_file():
    """La page demande le fichier GPX et l'envoie en relecture ; c'est le seul champ, puisque c'est le seul envoyé."""
    page = add_hike_page()
    assert 'id="gpxFileInput" accept=".gpx"' in page
    assert "Envoyer en relecture" in page
    assert page.count("<input") == 1


def test_add_hike_page_no_longer_shows_lost_fields():
    """Les champs perdus sans message (nom, récit, photos) et le faux brouillon ont disparu ; vu pendant l'issue #266."""
    page = add_hike_page()
    for lost in ("Nom de la randonnée", "Ton récit du parcours", "Glisse 1 à 3 photos", "Enregistrer le brouillon"):
        assert lost not in page


def test_add_hike_page_hides_the_load_anyway_button_until_the_api_offers_it():
    """Le bouton « Charger quand même » est sur la page mais caché : contrib.js ne l'affiche qu'à l'admin, après le refus d'un tracé qui suit une rando en base."""
    page = add_hike_page()
    assert 'id="loadAnyway" style="display:none;' in page
    assert "Charger quand même" in page
