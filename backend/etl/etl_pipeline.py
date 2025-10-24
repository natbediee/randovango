from backend.utils.mysql_utils import MySQLUtils
from backend.etl.extract.scraper_p4n import run_p4n_scraper
from backend.etl.transform.transform_p4n import transform_p4n
from backend.etl.load.load_p4n import load_p4n_to_mysql
import os
from backend.utils.logger_util import LoggerUtil
from pathlib import Path
from backend.utils.path_utils import add_etl_paths
from backend.etl.transform.transform_gpx import transform_gpx
from backend.etl.load.load_gpx import load_gpx_data
from backend.etl.extract.api_meteo import fetch_weather_data
from backend.utils.service_utils import ServiceUtil

# À compléter avec les autres modules d'extraction
# from backend.etl.extract.api_osm import extract_osm
# from backend.etl.extract.api_wikidata import extract_wikidata

ROOT = Path(__file__).resolve().parents[2]
add_etl_paths(ROOT)

logger = LoggerUtil.get_logger("etl_pipeline")

def main():
    # 1. Import GPX (Mongo + MySQL) et récupération de la ville
    ServiceUtil.load_env()
    gpx_dir = ServiceUtil.get_env('DATA_GPX', 'data/in/gpx')
    gpx_files = [f for f in os.listdir(gpx_dir) if f.endswith('.gpx')]
    if not gpx_files:
        logger.error(f"[ETL] Aucun fichier GPX trouvé dans {gpx_dir}")
        return
    logger.info(f"[ETL] Début du pipeline. Fichier GPX détecté: {gpx_files[0]}")
    fname = gpx_files[0]
    gpx_path = os.path.join(gpx_dir, fname)
    with open(gpx_path, 'r') as gpx_file:
        gpx_content = gpx_file.read()
    # --- Transformation explicite ---
    data = transform_gpx(gpx_content, fname)
    if not data:
        logger.info("[ETL] Erreur lors de la transformation GPX. Arrêt du pipeline.")
        return
    # --- Chargement explicite ---
    city = load_gpx_data(data, gpx_path)
    if not city:
        logger.info("[ETL] Aucun nouveau fichier GPX à traiter. Arrêt du pipeline.")
        return
    logger.info(f"[ETL] Ville extraite du GPX: {city}")

    # 2. Extraction météo pour la ville
    try:
        logger.info(f"[ETL] Extraction météo pour la ville: {city}")
        fetch_weather_data(city)
    except Exception as e:
        logger.error(f"[ETL] Erreur lors de l'extraction météo: {e}")
        return

    # 3. Extraction P4N si la ville n'est pas déjà présente dans city_spot_scraped
    def city_already_scraped(city_name):
        conn = MySQLUtils.connect()
        cursor = MySQLUtils.get_cursor(conn)
        cursor.execute("SELECT COUNT(*) FROM histo_scrapt hs JOIN cities c ON hs.city_id = c.id WHERE c.name = %s", (city_name,))
        count = cursor.fetchone()[0]
        cursor.close()
        MySQLUtils.disconnect(conn)
        return count > 0

    if city_already_scraped(city):
        logger.info(f"[ETL] Ville déjà présente dans city_spot_scraped : {city}. Extraction P4N sautée.")
    else:
        try:
            logger.info(f"[ETL] Extraction P4N pour la ville : {city}")
            df_p4n = run_p4n_scraper(city, is_headless=True, save_csv=False)
            if df_p4n is not None:
                df_transformed = transform_p4n(df_p4n)
                # Export du DataFrame transformé pour tests/debug
                df_transformed.to_csv(f"/tmp/p4n_transformed_{city.replace(' ', '_')}.csv", sep=';', index=False, encoding='utf-8')
                logger.info(f"[ETL] DataFrame transformé exporté dans /tmp/p4n_transformed_{city.replace(' ', '_')}.csv")
                load_p4n_to_mysql(df_transformed)
                logger.info(f"[ETL] P4N chargé pour la ville : {city}")
            else:
                logger.warning(f"[ETL] Scraping P4N a échoué pour la ville : {city}")
        except Exception as e:
            logger.error(f"[ETL] Erreur lors de l'extraction/chargement P4N: {e}")

    logger.info("[ETL] Pipeline terminé.")

if __name__ == "__main__":
    main()
