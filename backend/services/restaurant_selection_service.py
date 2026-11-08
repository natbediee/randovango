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
import json
from datetime import date
from urllib.parse import quote_plus

# Une liste fixe : le genre, écrit librement, classait Ar Dagenta en bistrot puis en pizzeria.
# La même grille dans toute la France (8 novembre 2026) : l'ancienne était bretonne (crêperie), et « traditionnel » mêlait
# couscous, buffet asiatique, kebab et brasserie d'hôtel. Le nom local reste dans le genre : une crêperie, une winstub ou
# un bouchon sont de la cuisine régionale. « poisson » seulement si une page dit que la carte en est surtout faite.
TABLE_CATEGORIES = ["regionale", "poisson", "gastronomique", "bistrot", "pizzeria", "monde", "rapide", "plage", "francaise"]
# Les tables de la commune montrées au voyageur, les plus proches du spot. 15 : le plus de tables d'une commune cherchée
# d'un seul tenant (Le Conquet, novembre 2026), et le plus de lieux qu'une recherche de l'agent garde.
TABLES_SHOWN = 15
TABLE_CATEGORY_LABELS = {"regionale": "Cuisine régionale", "poisson": "Poisson et fruits de mer", "gastronomique": "Gastronomique",
                         "bistrot": "Bistrot, brasserie", "pizzeria": "Pizzeria, italien", "monde": "Cuisine du monde",
                         "rapide": "Restauration rapide", "plage": "Plage, guinguette", "francaise": "Cuisine française"}
NEW_MONTHS = 12
FRENCH_MONTHS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
                 "septembre", "octobre", "novembre", "décembre")
CONFIRMED_SEASON = "confirmee"
PROBABLE_SEASON = "probable"
MAPS_SEARCH_URL = "https://www.google.com/maps/search/?api=1&query="


def is_new(since: date | None, today: date | None = None) -> bool:
    """Le lieu est-il au registre depuis moins de NEW_MONTHS mois ?"""
    if not since:
        return False
    today = today or date.today()
    return (today.year - since.year) * 12 + today.month - since.month < NEW_MONTHS


def maps_url(name: str, address: str | None, latitude: float | None = None, longitude: float | None = None,
             generic: bool = False) -> str:
    """
    Le lien de recherche que Google autorise (guide « geo-guidelines »). Nos agents n'ouvrent jamais cette page.
    Le nom et l'adresse pour un lieu qui a les deux ; la position pour un lieu sans adresse ou au nom générique
    (« Laverie », « Point d'eau potable ») : chercher « Laverie » ferait sortir n'importe quelle laverie.
    """
    if (generic or not address) and latitude is not None and longitude is not None:
        return MAPS_SEARCH_URL + quote_plus(f"{float(latitude):.6f},{float(longitude):.6f}")
    return MAPS_SEARCH_URL + quote_plus(f"{name} {address or ''}".strip())


def open_months(months) -> list:
    """poi.mois_ouverture, lu par MySQL comme du texte JSON (« [3, 4, 5] », janvier = 0), ou une liste."""
    if isinstance(months, str):
        months = json.loads(months)
    return [int(month) for month in months or []]


def is_out_of_season(statut: str | None, months, day: date) -> bool:
    """
    Le lieu est-il fermé ce jour-là ? Seulement si sa saison est confirmée, avec ses mois (décision du 7 novembre 2026 :
    un lieu hors saison au jour du voyage est masqué, Kervouroc ne vend sa pêche que d'avril à octobre).
    Un saisonnier « probable », sans mois, reste montré avec une mention : on ne peut pas trancher pour le voyageur.
    """
    listed = open_months(months)
    return statut == CONFIRMED_SEASON and bool(listed) and day.month - 1 not in listed


def season_label(statut: str | None, months) -> str | None:
    """« Ouvert d'avril à octobre », ou « Saisonnier, vérifie l'ouverture » sans mois connus, sinon None."""
    listed = open_months(months)
    if statut == CONFIRMED_SEASON and listed:
        if len(listed) >= 12:
            return None
        # Le premier mois est celui qui suit un mois fermé : « de novembre à février » passe le nouvel an.
        first = next(month for month in listed if (month - 1) % 12 not in listed)
        last = next(month for month in listed if (month + 1) % 12 not in listed)
        start = FRENCH_MONTHS[first]
        return f"Ouvert {'d' + chr(39) if start[0] in 'aeiouéo' else 'de '}{start} à {FRENCH_MONTHS[last]}"
    if statut in (CONFIRMED_SEASON, PROBABLE_SEASON):
        return "Saisonnier, vérifie l'ouverture"
    return None
