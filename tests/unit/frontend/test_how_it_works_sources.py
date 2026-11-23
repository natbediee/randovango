"""
« Comment ça marche » dit d'où viennent vraiment les données, sans promettre ce qui n'existe pas (issue #302).
Page rendue par le vrai front Flask, comme test_vany_entries.py.
"""
# pytest met le dossier de ce test dans le chemin d'import (pas de __init__.py) : on importe le fichier voisin.
from test_free_limit_page import load_front


def render_how_it_works():
    """Le HTML de la page « Comment ça marche »."""
    return load_front().test_client().get("/how-it-works").get_data(as_text=True)


def test_how_it_works_says_where_data_comes_from():
    """La frise dit d'où viennent les spots (des van-lifers), les randos (sites de randonnée) et les services."""
    page = render_how_it_works()
    assert "repéré par des van-lifers" in page
    assert "Des tracés de sites de randonnée, avec" in page
    assert "réuni autour de ton spot et toujours à jour" in page


def test_how_it_works_drops_false_promises():
    """La page ne dit plus que chaque spot vient d'un contributeur relu avant publication (faux : la source des spots)."""
    page = render_how_it_works()
    assert "relus avant publication" not in page
    assert "contributeurs locaux" not in page
    assert "décrites par des van-lifers" not in page
    assert "autant de jours que tu veux" not in page


def test_how_it_works_announces_contributing_as_coming_soon():
    """L'encart contributeur annonce le partage de randos et de spots comme à venir, sans bouton qui mène nulle part."""
    page = render_how_it_works()
    assert "Bientôt, tu pourras partager tes randos et tes spots secrets" in page
    assert "Devenir contributeur" not in page


def test_how_it_works_shows_the_five_daily_steps():
    """La boucle d'une journée montre les cinq étapes du planificateur, pépites comprises."""
    page = render_how_it_works()
    assert "Cinq étapes, toujours dans le même ordre" in page
    assert "Ajoute tes pépites" in page
