"""
L'entrée de la supervision mène au Bilan (carte #186) : il résume ce qui reste à trancher et mène à chaque file.
Rendu par le vrai front Flask, comme test_free_limit_page.py.
"""
# pytest met le dossier de ce test dans le chemin d'import (pas de __init__.py) : on importe le fichier voisin par
# son nom. « tests.unit… » ne marchait qu'en lançant « python -m pytest », pas « pytest » comme la CI.
from test_free_limit_page import load_front


def test_the_supervision_button_opens_the_summary():
    """Le bouton « Supervision » du tableau de bord contributeur ouvre le Bilan, pas la page des spots."""
    page = load_front().test_client().get("/contributor").get_data(as_text=True)
    assert 'href="/supervision/bilan" class="btn btn--dark btn--sm" data-admin-only' in page


def test_the_supervision_address_of_the_app_is_the_summary():
    """L'adresse « supervision » que connaissent les scripts de l'appli (APP_URLS) est celle du Bilan."""
    page = load_front().test_client().get("/contributor").get_data(as_text=True)
    assert 'supervision: "/supervision/bilan"' in page


def test_the_app_knows_the_address_of_modifier():
    """La page Services renvoie vers Modifier quand une ville n'a plus rien à relire : l'appli connaît son adresse."""
    page = load_front().test_client().get("/contributor").get_data(as_text=True)
    assert 'supervisionModifier: "/supervision/modifier"' in page
