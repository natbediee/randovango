"""
Ce que le voyageur voit sur chaque commerce de l'étape 4 : même principe que les restaurants
(restaurant_selection_service.py). Les commerces vont du plus proche au plus loin, la mention « nouveau »
vient de la date du registre, et le bouton Google Maps laisse les avis au jugement du voyageur.

LES SUPERMARCHÉS ET LES CAFÉS ONT LEUR ONGLET
L'agent des commerces ne cherche que les commerces de proximité et les cafés (décision de l'utilisatrice du 7 novembre
2026) ; les supermarchés ont leur propre agent depuis le 11 novembre 2026 (agents/find_supermarches.py). Les trois
écrivent leurs fiches dans la table commerces : la catégorie de la fiche dit l'onglet (OWN_TAB).
"""
from utils.service_utils import POI_FRONTEND_CATEGORY_MAP

# Les services OSM de l'onglet « commerce » (pas les supermarchés, qui ont le leur) : là où l'agent est passé,
# seuls ceux qui ont une fiche sont montrés (api/routers/step4.py).
COMMERCE_SERVICES = tuple(category for category, tab in POI_FRONTEND_CATEGORY_MAP.items() if tab == "commerce")
# Les cafés et bars ont leur onglet (7 novembre 2026) : l'agent commerces les cherche, celui des restaurants non.
CAFE_SERVICES = tuple(category for category, tab in POI_FRONTEND_CATEGORY_MAP.items() if tab == "cafe")
SUPERMARKET_SERVICES = tuple(category for category, tab in POI_FRONTEND_CATEGORY_MAP.items() if tab == "supermarche")
# Une liste fixe, comme celle des restaurants : le genre, écrit librement, ne range pas deux passages pareil.
# Cave et Gourmandises (8 novembre 2026) : rangées avant en épicerie, des chocolateries s'y retrouvaient.
# Artisan (8 novembre 2026) : boucher, poissonnier, fromager, traiteur, rangés avant avec les producteurs. Sur 162 fiches
# « Producteur, artisan », 99 étaient des boutiques, affichées « Vente à la ferme » (Au Bœuf Charolais).
SHOP_CATEGORIES = ["boulangerie", "epicerie", "cave", "gourmandise", "artisan", "marche", "producteur", "cafe"]
SHOP_CATEGORY_LABELS = {"boulangerie": "Boulangerie", "epicerie": "Épicerie, supérette", "cave": "Cave",
                        "gourmandise": "Gourmandises", "artisan": "Boucherie, poissonnerie, fromagerie",
                        "marche": "Marché", "producteur": "Producteur, ferme", "cafe": "Café, bar",
                        "supermarche": "Supermarché"}
# Le service OSM de chaque catégorie : un commerce créé par l'agent rejoint l'onglet « commerce »
# (utils/service_utils.POI_FRONTEND_CATEGORY_MAP) et le carnet affiche le nom de ce service.
SHOP_SERVICES = {"boulangerie": "bakery", "epicerie": "convenience", "cave": "wine", "gourmandise": "confectionery",
                 "artisan": "butcher",
                 "marche": "marketplace", "producteur": "farm", "cafe": "cafe", "supermarche": "supermarket"}
# Les commerces de la commune montrés au voyageur, les plus proches du spot : la même limite que les tables.
SHOPS_SHOWN = 15
MARKET = "marche"
CAFE = "cafe"
PRODUCER = "producteur"
SUPERMARKET = "supermarche"
# Les fiches de la table commerces qui ont leur propre onglet à l'étape 4 : {catégorie de la fiche : services de l'onglet}.
# Là où leur agent est passé, seuls ceux qui ont une fiche de cette catégorie sont montrés (step4.keep_checked_commerces)
# et triés (poi_triage_service.CHAINS). Toutes les autres catégories vont dans l'onglet « commerce ».
OWN_TAB = {CAFE: CAFE_SERVICES, SUPERMARKET: SUPERMARKET_SERVICES}
# Les onglets où seuls les services prouvés sont montrés, partout, même là où l'agent n'est jamais passé.
# Les supermarchés (décision de l'utilisatrice, 13 novembre 2026, #130) : OSM ne suit ni les déménagements ni les
# changements d'enseigne (Lidl de Saint-Renan et de Crozon, Super U de Saint-Renan devenu Carrefour). La règle du code
# postal laissait pourtant le Leclerc et l'Aldi d'OSM de Guilers, commune où l'agent ne passe pas, dans l'onglet de
# Saint-Renan. Sans preuve, pas de présentation.
PROVEN_ONLY_TABS = (SUPERMARKET,)
