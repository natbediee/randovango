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
}

# Mapping label -> type OSM/Wikidata (pour import ou reverse)
SERVICE_LABEL_TO_CATEGORY_MAP = {v: k for k, v in SERVICE_CATEGORY_LABEL_MAP.items()}

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
        Charge le fichier d'environnement (.env) et affiche un log si absent.
        """
        from pathlib import Path
        env_path = Path(".env")
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
