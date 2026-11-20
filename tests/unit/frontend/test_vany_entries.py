"""
Le parcours réel ne mène plus vers le chat de Vany sans dire qu'il n'est qu'un aperçu (issue #265).
Pages rendues par le vrai front Flask, comme test_free_limit_page.py ; ce qui se passe au clic, dans le navigateur, est vérifié à la main dans une vraie page.
"""
# pytest met le dossier de ce test dans le chemin d'import (pas de __init__.py) : on importe le fichier voisin.
from test_free_limit_page import load_front

PREVIEW_TAG = "Aperçu · bientôt disponible"
# La fin du libellé « Voir l'aperçu de Vany » : Jinja écrit l'apostrophe &#39; quand elle passe par une variable.
PREVIEW_BUTTON = "aperçu de Vany</a>"


def render(path):
    """Le HTML d'une page du front."""
    return load_front().test_client().get(path).get_data(as_text=True)


def test_duration_page_says_vany_is_a_preview():
    """Sur la page Durée, le bouton de l'encart de Vany annonce un aperçu, sans étiquette en double au-dessus du titre."""
    page = render("/duration")
    assert PREVIEW_TAG not in page
    assert PREVIEW_BUTTON in page
    assert "Discuter avec Vany" not in page


def test_trip_summary_says_vany_is_a_preview():
    """Sur le récap du voyage, le bouton de l'encart de Vany annonce un aperçu, sans étiquette en double au-dessus du titre."""
    page = render("/results")
    assert PREVIEW_TAG not in page
    assert PREVIEW_BUTTON in page
    assert "Découvrir Vany" not in page


def test_how_it_works_says_vany_is_coming_soon():
    """« Comment ça marche » annonce Vany et son prix comme à venir, pas comme une offre en vente."""
    page = render("/how-it-works")
    assert PREVIEW_TAG in page
    assert "Bientôt : 4,90 € par voyage" in page
    assert "Discuter avec Vany" not in page
