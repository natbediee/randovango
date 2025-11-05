from utils.logger_util import LoggerUtil
from etl.extract.api_meteo import extract_weather_data
from etl.load.load_meteo import load_weather_data

def run_meteo_etl(city_name: str) -> dict:
    logger = LoggerUtil.get_logger("etl_meteo")
    logger.info(f"[ETL] : Début ETL météo pour la ville : {city_name}")
    try:
        meteo_data = extract_weather_data(city_name)
        if not meteo_data:
            logger.warning(f"[ETL] : Pas de données météo extraites pour {city_name}")
            return {"warning": f"Pas de données météo pour {city_name}"}
        load_result = load_weather_data(meteo_data, city_name)
        logger.info(f"[ETL] : Données météo extraites et chargées pour {city_name}")
        return {"city": city_name, "meteo": meteo_data, "load_result": load_result}
    except Exception as e:
        logger.error(f"[ETL] : Erreur lors du traitement de la ville {city_name} : {e}")
        return {"error": str(e), "city": city_name}


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python3 -m etl.etl_meteo <city_name>")
        sys.exit(1)
    city_name = sys.argv[1]
    result = run_meteo_etl(city_name)
    print(result)
