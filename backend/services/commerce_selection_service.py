"""
Ce que le voyageur voit sur chaque commerce de l'étape 4 : même principe que les restaurants
(restaurant_selection_service.py). Les commerces vont du plus proche au plus loin, la mention « nouveau »
vient de la date du registre, et le bouton Google Maps laisse les avis au jugement du voyageur.

LES SUPERMARCHÉS RESTENT À PART
Décision de l'utilisatrice (7 novembre 2026) : ils gardent leur onglet, venu d'OSM. L'agent ne cherche que les
commerces de proximité : boulangerie, épicerie ou supérette, marché, producteur.
"""
from utils.service_utils import POI_FRONTEND_CATEGORY_MAP

# Les services OSM de l'onglet « commerce » (pas les supermarchés, qui ont le leur) : là où l'agent est passé,
# seuls ceux qui ont une fiche sont montrés (api/routers/step4.py).
COMMERCE_SERVICES = tuple(category for category, tab in POI_FRONTEND_CATEGORY_MAP.items() if tab == "commerce")
# Les cafés et bars ont leur onglet (7 novembre 2026) : l'agent commerces les cherche, celui des restaurants non.
CAFE_SERVICES = tuple(category for category, tab in POI_FRONTEND_CATEGORY_MAP.items() if tab == "cafe")
# Une liste fixe, comme celle des restaurants : le genre, écrit librement, ne range pas deux passages pareil.
# Le boucher, le poissonnier et le fromager vont avec les producteurs (« Producteur, artisan »).
SHOP_CATEGORIES = ["boulangerie", "epicerie", "marche", "producteur", "cafe"]
SHOP_CATEGORY_LABELS = {"boulangerie": "Boulangerie", "epicerie": "Épicerie, supérette", "marche": "Marché",
                        "producteur": "Producteur, artisan", "cafe": "Café, bar"}
# Le service OSM de chaque catégorie : un commerce créé par l'agent rejoint l'onglet « commerce »
# (utils/service_utils.POI_FRONTEND_CATEGORY_MAP) et le carnet affiche le nom de ce service.
SHOP_SERVICES = {"boulangerie": "bakery", "epicerie": "convenience", "marche": "marketplace", "producteur": "farm", "cafe": "cafe"}
# Les commerces de la commune montrés au voyageur, les plus proches du spot : la même limite que les tables.
SHOPS_SHOWN = 15
MARKET = "marche"
CAFE = "cafe"
