
from utils.mysql_utils import MySQLUtils
from etl.extract.scraper_p4n import run_p4n_scraper
from etl.transform.transform_p4n import transform_p4n
from etl.load.load_p4n import load_p4n_to_mysql
from etl.extract.api_osm import extract_osm
from etl.extract.api_wikidata import extract_wikidata
from etl.transform.transform_osm import transform_osm
from etl.transform.transform_wikidata import transform_wikidata
from etl.load.load_poi import load_osm_poi,load_wikidata_poi
from utils.logger_util import LoggerUtil
from etl.load.load_gpx import load_gpx_data
from etl.extract.api_meteo import extract_weather_data
from etl.load.load_meteo import load_weather_data
from etl.extract.gpx import extract_gpx_file


logger = LoggerUtil.get_logger("etl_pipeline")

def main():
    # 1. Import GPX (Mongo + MySQL) et récupération de la ville
    data, gpx_path, fname = extract_gpx_file()
    if not data:
        return
    # --- Chargement explicite ---
    city = load_gpx_data(data, gpx_path)
    if not city:
        logger.info("[ETL] Aucun nouveau fichier GPX à traiter. Arrêt du pipeline.")
        return
    logger.info(f"[ETL] Ville extraite du GPX: {city}")

    # 2. Extraction et chargement météo pour la ville
    try:
        logger.info(f"[ETL] Extraction météo pour la ville: {city}")
        weather_data = extract_weather_data(city)
        if weather_data:
            load_weather_data(weather_data, city)
            logger.info(f"[ETL] Données météo chargées pour la ville: {city}")
        else:
            logger.warning(f"[ETL] Aucune donnée météo à charger pour la ville: {city}")
    except Exception as e:
        logger.error(f"[ETL] Erreur lors de l'extraction/chargement météo: {e}")
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
                load_p4n_to_mysql(df_transformed,city)
                logger.info(f"[ETL] P4N chargé pour la ville : {city}")
            else:
                logger.warning(f"[ETL] Scraping P4N a échoué pour la ville : {city}")
        except Exception as e:
            logger.error(f"[ETL] Erreur lors de l'extraction/chargement P4N: {e}")

    # 4. Extraction OSM
    try:
        logger.info(f"[ETL] Extraction OSM pour la ville : {city}")
        osm_json = extract_osm(city)
        logger.info("[ETL] Transformation OSM...")
        df_osm = transform_osm(osm_json, city=city)
        logger.info("[ETL] Chargement OSM...")
        load_osm_poi(df_osm=df_osm, city_name=city)
    except Exception as e:
        logger.error(f"[ETL] Erreur OSM: {e}")

    # 5. Extraction Wikidata
    try:
        logger.info(f"[ETL] Extraction Wikidata pour la ville : {city}")
        wikidata_json = extract_wikidata(city)
        logger.info("[ETL] Transformation Wikidata...")
        df_wiki = transform_wikidata(wikidata_json=wikidata_json, city_name=city)
        logger.info("[ETL] Chargement Wikidata...")
        load_wikidata_poi(df_wiki=df_wiki, city_name=city)
    except Exception as e:
        logger.error(f"[ETL] Erreur Wikidata: {e}")

    logger.info("[ETL] Pipeline terminé.")

if __name__ == "__main__":
    main()
