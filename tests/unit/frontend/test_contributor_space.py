"""
L'espace contributeur sépare ce qui marche déjà de l'aperçu de ce qu'il deviendra (issue #265).
Pages rendues par le vrai front Flask, comme test_free_limit_page.py.
"""
# pytest met le dossier de ce test dans le chemin d'import (pas de __init__.py) : on importe le fichier voisin.
from test_free_limit_page import load_front


def render(path):
    """Le HTML d'une page du front."""
    return load_front().test_client().get(path).get_data(as_text=True)


def test_examples_are_grouped_under_a_preview_block():
    """Les compteurs, contributions et codes Vany d'exemple sont sous « Bientôt dans ton espace », marqués « exemple »."""
    page = render("/contributor")
    preview = page.index("Bientôt dans ton espace")
    assert "Aperçu · exemple" in page
    assert "Les chiffres et les codes ci-dessous sont des exemples." in page
    assert page.index("spots partagés") > preview
    assert page.index("Tes codes Vany") > preview


def test_real_actions_come_before_the_preview_block():
    """L'ajout d'une randonnée, qui marche vraiment, reste au-dessus de l'aperçu."""
    page = render("/contributor")
    assert page.index("+ Ajouter une randonnée") < page.index("Bientôt dans ton espace")


def test_preview_buttons_are_gone():
    """Aucun bouton de l'aperçu ne fait croire à une action : ni « Copier », ni « Parler à Vany », ni « Tout voir »."""
    page = render("/contributor")
    for label in ("Copier</button>", "Parler à Vany", "Tout voir", "Voir ton impact"):
        assert label not in page


def test_login_page_announces_future_benefits_as_coming_soon():
    """La page de connexion annonce le suivi d'impact et Vany offert comme à venir, sans la citation inventée."""
    page = render("/contributor/login")
    assert "Bientôt : tu suivras ton impact" in page
    assert "Bientôt : le chat 100% IA avec Vany" in page
    assert "214 nuits" not in page
