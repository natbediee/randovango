import requests

from utils.logger_util import LoggerUtil
from utils.geo_utils import get_coordinates_for_city

logger = LoggerUtil.get_logger("etl_meteo")

def extract_weather_data(city) -> bool | None:
    """
    Récupère les données météo pour une ville donnée via l'API Open-Meteo.
    """

    logger.info(f"[Extract] : Recherche des coordonnées pour {city}")
    BASE_URL = "https://api.open-meteo.com/v1/forecast"
    latitude, longitude = get_coordinates_for_city(city)

    if latitude is None or longitude is None:
        logger.warning(f"[Extract] : Impossible de trouver les coordonnées pour {city}")
        return None
    logger.info(f"[Extract] : Coordonnées trouvées: {latitude}, {longitude}")

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
        logger.info("[Extract] : Appel de l'API météo...")
        response = requests.get(BASE_URL, params=params)
        response.raise_for_status()
        data = response.json()
        daily_data = data.get('daily', {})
        weather_list = []
        # Transformation des données en une liste de tuples pour l'insertion SQL
        for i in range(len(daily_data.get('time', []))):
            weather_tuple = (
                daily_data['time'][i],
                daily_data['temperature_2m_max'][i],
                daily_data['temperature_2m_min'][i],
                daily_data['precipitation_sum'][i],
                daily_data['wind_speed_10m_max'][i],
                daily_data['weather_code'][i],
                daily_data['shortwave_radiation_sum'][i]
            )
            weather_list.append(weather_tuple)

        logger.info(f"[Extract] : {len(weather_list)} jours de prévisions récupérés")
        return weather_list
    except requests.exceptions.RequestException as e:
        logger.error(f"[Extract] : Échec de l'extraction API météo : {e}")
        return None

