"""
La page d'accès à Vany (frontend/templates/pages/unlock_vany.html) n'est qu'un aperçu : le paiement et les codes
contributeur n'existent pas encore (issue #265). Page rendue par le vrai front Flask, comme test_free_limit_page.py.
"""
# pytest met le dossier de ce test dans le chemin d'import (pas de __init__.py) : on importe le fichier voisin.
from test_free_limit_page import load_front


def unlock_page():
    """Le HTML de la page d'accès à Vany."""
    return load_front().test_client().get("/unlock-vany").get_data(as_text=True)


def test_unlock_page_says_it_is_a_preview():
    """Dès l'ouverture, la page dit que le paiement et les codes contributeur ne sont pas encore en service."""
    page = unlock_page()
    assert "Aperçu · bientôt disponible" in page
    assert "Le paiement et les codes contributeur ne sont pas encore en service" in page


def test_payment_and_code_buttons_are_disabled():
    """Ni le paiement ni le code ne peuvent être lancés ; avant, un faux « Paiement… » ouvrait le chat."""
    page = unlock_page()
    assert "disabled>Paiement bientôt disponible</button>" in page
    assert "disabled>Codes bientôt disponibles</button>" in page
    assert "Payer et discuter avec Vany" not in page
    assert "js/unlock.js" not in page


def test_unlock_page_leads_to_the_chat_preview():
    """Le seul bouton actif mène à l'aperçu du chat, annoncé comme tel."""
    assert 'href="/chat" class="btn btn--primary">Voir l\'aperçu du chat</a>' in unlock_page()
