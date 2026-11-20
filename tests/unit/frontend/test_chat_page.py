"""
Le chat de Vany (frontend/templates/pages/chat.html) n'est qu'un aperçu : chat.js joue une conversation écrite
à l'avance (issue #265). Page rendue par le vrai front Flask, comme test_free_limit_page.py ; la conversation
elle-même, jouée dans le navigateur, est vérifiée à la main.
"""
# pytest met le dossier de ce test dans le chemin d'import (pas de __init__.py) : on importe le fichier voisin.
from test_free_limit_page import load_front


def chat_page():
    """Le HTML de la page du chat."""
    return load_front().test_client().get("/chat").get_data(as_text=True)


def test_chat_says_it_is_a_preview_before_the_first_message():
    """Avant toute réponse, le chat dit que Vany ne répond pas encore et que l'échange est un exemple écrit à l'avance."""
    page = chat_page()
    assert "Aperçu · bientôt disponible" in page
    assert "Vany ne répond pas encore pour de vrai" in page
    assert "n'enregistre aucun voyage" in page


def test_chat_reminds_under_the_input_that_answers_are_written_in_advance():
    """Sous la zone de saisie, un rappel dit que les réponses sont écrites à l'avance."""
    assert "Aperçu : les réponses de Vany sont écrites à l'avance." in chat_page()
