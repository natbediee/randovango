import os
from dotenv import load_dotenv

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
    # Restauration
    "restaurant":             "restauration",
    "cafe":                   "restauration",
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
    "viewpoint":              "culture",
    "hiking":                 "culture",
    "bicycle":                "culture",
    "motorcycle":             "culture",
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
    "Belle balade à moto": "motorcycle",
    "Escalade (Sites d')": "climbing",
}


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
        """
        Charge le fichier d'environnement (.env). Chemin absolu ancré sur ce fichier
        (et non relatif au répertoire courant) : un chemin relatif ne fonctionnait
        que par accident, grâce à db_utils.py qui charge le même .env en absolu et
        s'importe généralement avant (python-dotenv ne réécrit pas les variables
        déjà présentes) — mais cassait dès qu'un module appelait load_env() sans
        que db_utils ait été importé au préalable (ex: script isolé, ou MongoUtils
        appelé depuis un chemin de code qui n'importe jamais MySQLUtils).
        """
        from pathlib import Path
        env_path = Path(__file__).resolve().parents[2] / ".env"
        load_dotenv(str(env_path))


    @staticmethod
    def get_env(var: str, default: str = "") -> str:
        """
        Récupère la variable d'environnement {var} ou la valeur {default} si absente.
        """
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
