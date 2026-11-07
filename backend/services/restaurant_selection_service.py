"""
Ce que le voyageur voit sur chaque table de l'étape 4.

DES TABLES SÛRES, CLASSÉES PAR DISTANCE, PAS UN CLASSEMENT DES MEILLEURES
Aucune note de clients n'est permise (voir pepite_common.EXCLUDED_SITES), et compter les sources ne classe presque rien :
sur 57 lieux visibles à Plougonvelin et au Conquet, 47 ont une source et 10 en ont deux. Un tour par catégorie, la distinction
en tête, a été essayé : il rejetait en fin de liste les tables à deux pas du spot. Les tables vont donc de la plus proche à la
plus loin (step4.order_category). Le bouton Google Maps laisse les avis au jugement du voyageur.

« NOUVEAU » PENDANT 12 MOIS
Une saison complète, d'après la date du registre. La date est comparée à l'affichage : la mention s'en va sans nouveau
passage. Le registre ne distingue pas une ouverture d'une reprise : Café Konk reprend la Taverne de Kermorvan.
"""
from datetime import date
from urllib.parse import quote_plus

# Une liste fixe : le genre, écrit librement, classait Ar Dagenta en bistrot puis en pizzeria.
TABLE_CATEGORIES = ["gastronomique", "poisson", "creperie", "pizzeria", "plage", "bistrot", "traditionnel"]
# Les tables de la commune montrées au voyageur, les plus proches du spot. 15 : le plus de tables d'une commune cherchée
# d'un seul tenant (Le Conquet, novembre 2026), et le plus de lieux qu'une recherche de l'agent garde.
TABLES_SHOWN = 15
TABLE_CATEGORY_LABELS = {"gastronomique": "Gastronomique", "poisson": "Poisson et fruits de mer", "creperie": "Crêperie", "pizzeria": "Pizzeria",
                         "plage": "Adresse de plage", "bistrot": "Bistrot, bar", "traditionnel": "Cuisine traditionnelle"}
NEW_MONTHS = 12
MAPS_SEARCH_URL = "https://www.google.com/maps/search/?api=1&query="


def is_new(since: date | None, today: date | None = None) -> bool:
    """Le lieu est-il au registre depuis moins de NEW_MONTHS mois ?"""
    if not since:
        return False
    today = today or date.today()
    return (today.year - since.year) * 12 + today.month - since.month < NEW_MONTHS


def maps_url(name: str, address: str | None) -> str:
    """Le lien de recherche que Google autorise (guide « geo-guidelines »). Nos agents n'ouvrent jamais cette page."""
    return MAPS_SEARCH_URL + quote_plus(f"{name} {address or ''}".strip())
