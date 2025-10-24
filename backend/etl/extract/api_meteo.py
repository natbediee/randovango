from pathlib import Path
import requests

from backend.utils.logger_util import LoggerUtil
from backend.etl.load.load_meteo import insert_weather_data
from backend.utils.geo_utils import get_coordinates_for_city
from backend.utils.mysql_utils import MySQLUtils

ROOT = Path(__file__).resolve().parents[3]

logger = LoggerUtil.get_logger("api_meteo")

# --- Fonction d'Extraction Météo (Paramétrée par Coordonnées) ---
def get_or_create_city(city_name, latitude, longitude) -> int:
    """
    Récupère l'ID de la ville depuis la table cities, ou la crée si elle n'existe pas.
    
    Returns:
        int: L'ID de la ville dans la table cities
    """
    cnx = MySQLUtils.connect()
    cursor = cnx.cursor()
    
    # Vérifier si la ville existe
    cursor.execute("SELECT id FROM cities WHERE name = %s", (city_name,))
    result = cursor.fetchone()
    
    if result:
        city_id = result[0]
        logger.info(f"Ville {city_name} trouvée avec ID={city_id}")
    else:
        # Créer la ville
        cursor.execute(
            "INSERT INTO cities (name, latitude, longitude) VALUES (%s, %s, %s)",
            (city_name, latitude, longitude)
        )
        cnx.commit()
        city_id = cursor.lastrowid
    logger.info(f"Ville {city_name} créée avec ID={city_id}")
    
    cursor.close()
    cnx.close()
    return city_id


def fetch_weather_data(city) -> bool | None:
    """
    Récupère les données météo pour une ville donnée via l'API Open-Meteo.
    """

    logger.info(f"Recherche des coordonnées pour {city}")
    BASE_URL = "https://api.open-meteo.com/v1/forecast"
    latitude, longitude = get_coordinates_for_city(city)

    if latitude is None or longitude is None:
        logger.warning(f"Impossible de trouver les coordonnées pour {city}")
        return None

    logger.info(f"Coordonnées trouvées: {latitude}, {longitude}")
    
    # Récupérer ou créer l'entrée de la ville dans la base
    city_id = get_or_create_city(city, latitude, longitude)

    # Paramètres de l'API Open-Meteo
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "timezone": "Europe/Paris",
        "daily": [
            "weather_code",
            "temperature_2m_max",
            "temperature_2m_min",
            "precipitation_sum",
            "wind_speed_10m_max",
            "shortwave_radiation_sum"
        ],
        "forecast_days": 7
    }

    try:
        logger.info("Appel de l'API météo...")
        response = requests.get(BASE_URL, params=params)
        response.raise_for_status()
        data = response.json()

        daily_data = data.get('daily', {})
        weather_list = []

        # Transformation des données en une liste de tuples pour l'insertion SQL
        for i in range(len(daily_data.get('time', []))):
            weather_tuple = (
                city_id,  # city_id récupéré depuis la table cities
                daily_data['time'][i],
                daily_data['temperature_2m_max'][i],
                daily_data['temperature_2m_min'][i],
                daily_data['precipitation_sum'][i],
                daily_data['wind_speed_10m_max'][i],
                daily_data['weather_code'][i],
                daily_data['shortwave_radiation_sum'][i]
            )
            weather_list.append(weather_tuple)

        logger.info(f"{len(weather_list)} jours de prévisions récupérés")
        # Appel direct à l'insertion en base
        insert_weather_data(weather_list)
        logger.info(f"Données météo insérées en base pour {city}")
        return True

    except requests.exceptions.RequestException as e:
        logger.error(f"Échec de l'extraction API météo : {e}")
        return None

if __name__ == "__main__":
    logger.info("[MAIN] Bloc main exécuté")
    print("[MAIN] Bloc main exécuté")
    import sys
    if len(sys.argv) < 2:
        print("Usage: python meteo.py <nom_de_la_ville>")
        logger.warning("Usage: python meteo.py <nom_de_la_ville>")
        sys.exit(1)
    city = sys.argv[1]
    logger.info(f"[MAIN] Ville demandée: {city}")
    print(f"[MAIN] Ville demandée: {city}")
    fetch_weather_data(city)


