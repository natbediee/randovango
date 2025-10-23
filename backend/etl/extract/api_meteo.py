# Import standard et tierces
from pathlib import Path
from dotenv import load_dotenv
import requests
import json
import os
import sys
import logging

# Import spécifique au projet
from geo_utils import get_coordinates_for_city

# Assurez-vous que ROOT est défini avant d'ajouter le chemin
ROOT = Path(__file__).resolve().parents[3]
sys.path.append(str(ROOT / "backend/etl/extraction"))

# Configuration du logging
logging.basicConfig(
    level=logging.DEBUG,  # Niveau de log (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),  # Affiche les logs dans la console
        logging.FileHandler(ROOT / "logs/api_meteo.log", mode='a', encoding='utf-8')  # Sauvegarde dans un fichier log
    ]
)

load_dotenv(ROOT / ".env")

# Chemin vers data/in
DATA_IN = ROOT / os.getenv("DATA_IN")/"meteo"

# --- Fonction d'Extraction Météo (Paramétrée par Coordonnées) ---
def fetch_weather_data(city):
    """
    Récupère les données météo pour une ville donnée via l'API Open-Meteo.
    """

    logging.info(f"Recherche des coordonnées pour {city}")
    BASE_URL = "https://api.open-meteo.com/v1/forecast"
    latitude, longitude = get_coordinates_for_city(city)

    if latitude is None or longitude is None:
        logging.warning(f"Impossible de trouver les coordonnées pour {city}")
        return None

    logging.info(f"Coordonnées trouvées: {latitude}, {longitude}")

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
        logging.info("Appel de l'API météo...")
        response = requests.get(BASE_URL, params=params)
        response.raise_for_status()
        data = response.json()

        daily_data = data.get('daily', {})
        weather_list = []

        # Transformation des données en une liste de jours
        for i in range(len(daily_data.get('time', []))):
            weather_day = {
                "date": daily_data['time'][i],
                "temp_max_c": daily_data['temperature_2m_max'][i],
                "temp_min_c": daily_data['temperature_2m_min'][i],
                "precipitation_mm": daily_data['precipitation_sum'][i],
                "wind_max_kmh": daily_data['wind_speed_10m_max'][i],
                "weather_code": daily_data['weather_code'][i],
                "solar_energy_sum": daily_data['shortwave_radiation_sum'][i]
            }
            weather_list.append(weather_day)

        logging.info(f"{len(weather_list)} jours de prévisions récupérés")

        # Définition du chemin de sauvegarde (data_input/raw)
        DATA_IN.mkdir(parents=True, exist_ok=True)
        filename = f'weather_data_{city.replace(" ", "_")}.json'
        file_path = DATA_IN / filename
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(weather_list, f, indent=4, ensure_ascii=False)

        logging.info(f"Données sauvegardées dans: {file_path}")
        return file_path

    except requests.exceptions.RequestException as e:
        logging.error(f"Échec de l'extraction API météo : {e}")
        return None

# --- BLOC DE LANCEMENT PARAMÉTRABLE ---

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python meteo.py <nom_de_la_ville>")
        sys.exit(1) 
    city = sys.argv[1]
    fetch_weather_data(city)
