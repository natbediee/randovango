"""
La page d'ajout d'une randonnée (frontend/templates/pages/add_hike.html) ne montre que ce qui est vraiment envoyé
à l'API : le fichier GPX (issue #265). Page rendue par le vrai front Flask, comme test_free_limit_page.py ;
l'envoi lui-même est vérifié à la main dans une vraie page.
"""
from pathlib import Path

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


def test_add_hike_page_shows_the_outside_france_warning_in_its_own_colour():
    """La page montre l'avertissement d'une rando partie hors de France dans une couleur à part : le script lit « warning » et la feuille de style a sa couleur (issue #272)."""
    front = Path(__file__).resolve().parents[3] / "frontend" / "static"
    script = (front / "js" / "contrib.js").read_text(encoding="utf-8")
    styles = (front / "css" / "app.css").read_text(encoding="utf-8")
    assert "data.warning" in script and "is-warn" in script
    assert ".addhike-msg.is-warn" in styles
