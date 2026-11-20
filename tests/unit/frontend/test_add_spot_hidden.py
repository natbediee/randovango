"""
L'ajout d'un spot est masqué tant que rien n'enregistre un spot proposé en base (issue #265).
Pages rendues par le vrai front Flask, comme test_free_limit_page.py.
"""
# pytest met le dossier de ce test dans le chemin d'import (pas de __init__.py) : on importe le fichier voisin.
from test_free_limit_page import load_front


def test_add_spot_address_leads_back_to_the_contributor_space():
    """L'ancienne adresse d'ajout d'un spot ramène à l'espace contributeur ; avant, elle répondait « Merci ! » sans rien envoyer."""
    response = load_front().test_client().get("/contributor/add-spot")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/contributor")


def test_contributor_space_offers_no_spot_to_add():
    """L'espace contributeur ne propose plus d'ajouter un spot, seulement une randonnée."""
    page = load_front().test_client().get("/contributor").get_data(as_text=True)
    assert "Ajouter un spot" not in page
    assert "+ Ajouter une randonnée" in page


def test_login_page_no_longer_invites_to_share_spots():
    """La page de connexion invite à partager des randonnées seulement, puisqu'un spot ne peut plus être proposé."""
    page = load_front().test_client().get("/contributor/login").get_data(as_text=True)
    assert "Connecte-toi pour partager tes randonnées." in page
    assert "partager tes spots" not in page
