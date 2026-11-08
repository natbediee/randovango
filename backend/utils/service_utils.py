import os
from pathlib import Path

from dotenv import load_dotenv

# Le fichier .env (mots de passe, jetons, réglages) est à la racine du projet,
# deux dossiers au-dessus de ce fichier : utils/ -> backend/ -> racine.
# Dans Docker, c'est /usr/src/.env (voir docker-compose.yml).
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"

 # Mapping OSM/Wikidata type -> label lisible (pour affichage front)
SERVICE_CATEGORY_LABEL_MAP = {
    'fuel': 'Station-service',
    'restaurant': 'Restaurant',
    'pharmacy': 'Pharmacie',
    'parking': 'Parking',
    'convenience': 'Supérette',
    'bakery': 'Boulangerie',
    'cafe': 'Café',
    'viewpoint': 'Point de vue',
    'attraction': 'Attraction',
    'beach': 'Plage',
    'drinking_water': "Point d'eau potable",
    'toilets': 'Toilettes',
    'shower': 'Douche publique',
    'sanitary_dump_station': 'Vidange camping-car',
    'waste_disposal': 'Poubelle',
    'shelter': 'Abri',
    'supermarket': 'Supermarché',
    'laundry': 'Laverie',
    'cinema': 'Cinéma',
    'theatre': 'Théâtre',
    'arts_centre': 'Centre culturel',
    'marketplace': 'Marché',
    'museum': 'Musée',
    'gallery': 'Galerie',
    'farm': 'Vente à la ferme',
    'brewery': 'Brasserie',
    # Les catégories de l'agent commerces sans service OSM à elles (8 novembre 2026, commerce_selection_service).
    'butcher': 'Boucherie, poissonnerie, fromagerie',
    'wine': 'Cave',
    'confectionery': 'Gourmandises',
}

# Mapping label -> type OSM/Wikidata (pour import ou reverse)
SERVICE_LABEL_TO_CATEGORY_MAP = {v: k for k, v in SERVICE_CATEGORY_LABEL_MAP.items()}

# Mapping service_category DB (raw OSM/Wikidata) -> onglet frontend (étape 4 + bilan).
# Volontairement non mappés (= ignorés, pas de catégorie "Autres" fourre-tout) :
# parking (doublon avec les spots pour dormir de l'étape 3), shelter, waste_disposal
# hors vidange officielle, internet_access, power_supply, pets, etc.
POI_FRONTEND_CATEGORY_MAP = {
    # Eau
    "drinking_water":         "eau",
    "water":                  "eau",
    # Vidange (séparée de l'eau : point dédié, souvent pas au même endroit)
    "sanitary_dump_station":  "vidange",
    # Gasoil
    "fuel":                   "gasoil",
    # Supermarché (séparé du commerce de proximité)
    "supermarket":            "supermarche",
    # Commerce
    "convenience":            "commerce",
    "bakery":                 "commerce",
    "shop":                   "commerce",
    "marketplace":            "commerce",
    "farm":                   "commerce",
    "brewery":                "commerce",
    "butcher":                "commerce",
    "wine":                   "commerce",
    "confectionery":          "commerce",
    # Restauration
    "restaurant":             "restauration",
    # Café, bar : un onglet à part (7 novembre 2026). La restauration ne garde que les endroits où l'on mange ;
    # les cafés sont cherchés par l'agent commerces (agents/find_commerces.py), jamais par celui des restaurants.
    "cafe":                   "cafe",
    # Laverie : un onglet à part, venu d'OSM seulement (pas d'agent, comme les supermarchés).
    "laundry":                "laverie",
    "fast_food":              "restauration",
    # Toilettes (séparée des douches : pas toujours au même endroit)
    "toilets":                "toilettes",
    # Hygiène (douches + baignade/piscine)
    "shower":                 "hygiene",
    "swimming":               "hygiene",
    "swimming_pool":          "hygiene",
    # Culture & Loisirs
    "tourism":                "culture",
    "attraction":             "culture",
    "museum":                 "culture",
    "gallery":                "culture",
    "cinema":                 "culture",
    "theatre":                "culture",
    "arts_centre":            "culture",
    "viewpoint":              "culture",
    "hiking":                 "culture",
    "bicycle":                "culture",
    "climbing":               "culture",
    "watersport":             "culture",
    "canoe":                  "culture",
    "fishing":                "culture",
    "playground":             "culture",
    "beach":                  "culture",
    # Urgences
    "pharmacy":               "urgence",
    "hospital":               "urgence",
    "doctors":                "urgence",
}

 # Mapping service → catégorie (p4n)
SERVICE_CATEGORY_MAP = {
    "Eaux usées": "sanitary_dump_station",
    "Boulangerie": "shop",
    "Monuments à visiter": "tourism",
    "Animaux autorisés": "pets",
    "Eau potable": "drinking_water",
    "Poubelle": "waste_disposal",
    "Toilettes": "toilets",
    "Douches (accès possible)": "shower",
    "Électricité (accès possible)": "power_supply",
    "Accès internet par WiFi": "internet_access",
    "Laverie": "laundry",
    "Baignade possible": "swimming",
    "Aire de jeux": "playground",
    "Eaux noires": "sanitary_dump_station",
    "Internet 3G/4G": "internet_access",
    "Pistes/balades de VTT": "bicycle",
    "Départ de randonnées": "hiking",
    "Point de vue": "viewpoint",
    "Coins de pêche": "fishing",
    "Windsurf/kitesurf (Spots de)": "watersport",
    "Pêche à pied": "fishing",
    "Canoë/kayak (Base de)": "canoe",
    "Dépannage en gaz": "fuel",
    "Station GPL": "fuel",
    "Piscine": "swimming_pool",
    "Escalade (Sites d')": "climbing",
    # Deux services P4N restés sans catégorie jusqu'ici (28 et 4 spots concernés) :
    # ils entraient en base via get_or_create_service_with_category avec category NULL.
    "Lavage pour camping-car": "car_wash",
    "Caravaneige": "caravan_site",
}

# Services p4n qu'on ne veut pas dans Randovango (hors sujet pour des
# randonneurs en van). Ils sont ignorés au chargement (etl/load/load_p4n.py) et
# supprimés de la base existante par le script ponctuel oneshot/clean_spots.py.
EXCLUDED_SERVICES = {
    "Belle balade à moto",
}


def is_excluded_service(service_name: str) -> bool:
    """True si ce service p4n ne doit pas entrer en base."""
    return service_name in EXCLUDED_SERVICES


class ServiceUtil:

    @staticmethod
    def get_or_create_service_with_category(cursor, service_name):
        """
        Insère le service (avec sa catégorie issue du mapping) dans la table services s'il n'existe pas, sinon retourne son id.
        """
        category = SERVICE_CATEGORY_MAP.get(service_name)
        cursor.execute("SELECT id FROM services WHERE name = %s", (service_name,))
        result = cursor.fetchone()
        if result:
            return result[0]
        cursor.execute("INSERT INTO services (name, category) VALUES (%s, %s)", (service_name, category))
        return cursor.lastrowid


    @staticmethod
    def load_env() -> None:
        """Charge les valeurs du fichier .env pour que get_env puisse les lire."""
        load_dotenv(ENV_FILE)

    @staticmethod
    def get_env(var: str, default: str = "") -> str:
        """Valeur d'une variable du .env, ou `default` si elle n'existe pas."""
        return os.getenv(var, default)

    @staticmethod
    def get_city_id(cursor,city_name):
        """
        Récupère l'ID de la ville depuis la table cities.
        """
        cursor.execute("SELECT id FROM cities WHERE name = %s", (city_name,))
        result = cursor.fetchone()
        if result:
            return result[0]
        return None
