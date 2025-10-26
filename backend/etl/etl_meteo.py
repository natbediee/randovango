from backend.utils.logger_util import LoggerUtil
from backend.etl.extract.api_meteo import extract_weather_data
from backend.etl.load.load_meteo import load_weather_data

def run_meteo_etl(city_name: str) -> dict:
    logger = LoggerUtil.get_logger("etl_meteo")
    # Extraction des données météo via api_meteo
    meteo_data = extract_weather_data(city_name)
    if not meteo_data:
        logger.warning(f"Pas de données météo extraites pour {city_name}")
        return {"warning": f"Pas de données météo pour {city_name}"}

    # Chargement des données météo en base
    load_result = load_weather_data(meteo_data, city_name)
    logger.info(f"Données météo extraites et chargées pour {city_name}")
    return {"city": city_name, "meteo": meteo_data, "load_result": load_result}
