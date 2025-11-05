
import threading
from utils.db_utils import MySQLUtils
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
from etl.extract.gpx import extract_all_gpx_files


logger = LoggerUtil.get_logger("etl_pipeline")

# Verrou pour empêcher plusieurs scrapings P4N en parallèle
scraping_lock = threading.Lock()

def scraping_background(city):
    """Fonction de scraping à exécuter en arrière-plan (thread séparé)"""
    logger.info(f"[ETL-BG] Début du scraping en arrière-plan pour la ville: {city}")
    
    # 1. Extraction OSM (rapide - API)
    try:
        logger.info(f"[ETL-BG] Extraction OSM pour la ville : {city}")
        osm_json = extract_osm(city)
        logger.info("[ETL-BG] Transformation OSM...")
        df_osm = transform_osm(osm_json, city=city)
        logger.info("[ETL-BG] Chargement OSM...")
        load_osm_poi(df_osm=df_osm, city_name=city)
        logger.info(f"[ETL-BG] OSM chargé pour la ville : {city}")
    except Exception as e:
        logger.error(f"[ETL-BG] Erreur OSM: {e}")

    # 2. Extraction Wikidata (rapide - API)
    try:
        logger.info(f"[ETL-BG] Extraction Wikidata pour la ville : {city}")
        wikidata_json = extract_wikidata(city)
        logger.info("[ETL-BG] Transformation Wikidata...")
        df_wiki = transform_wikidata(wikidata_json=wikidata_json, city_name=city)
        logger.info("[ETL-BG] Chargement Wikidata...")
        load_wikidata_poi(df_wiki=df_wiki, city_name=city)
        logger.info(f"[ETL-BG] Wikidata chargé pour la ville : {city}")
    except Exception as e:
        logger.error(f"[ETL-BG] Erreur Wikidata: {e}")

    # 3. Extraction P4N en dernier (lent - Selenium ~4min) si la ville n'est pas déjà présente dans histo_scrap
    def city_already_scraped(city_name):
        conn = MySQLUtils.connect()
        cursor = MySQLUtils.get_cursor(conn)
        cursor.execute("SELECT COUNT(*) FROM histo_scrap hs JOIN cities c ON hs.city_id = c.id WHERE c.name = %s", (city_name,))
        count = cursor.fetchone()[0]
        cursor.close()
        MySQLUtils.disconnect(conn)
        return count > 0

    # Verrou uniquement pour le scraping P4N (Selenium) pour éviter les conflits
    with scraping_lock:
        if city_already_scraped(city):
            logger.info(f"[ETL-SC] Ville déjà présente dans histo_scrap : {city}. Extraction P4N sautée.")
        else:
            try:
                logger.info(f"[ETL-SC] Extraction P4N pour la ville : {city} (scraping en cours...)")
                df_p4n = run_p4n_scraper(city, is_headless=True, save_csv=False)
                if df_p4n is not None:
                    df_transformed = transform_p4n(df_p4n)
                    load_p4n_to_mysql(df_transformed, city)
                    logger.info(f"[ETL-SC] P4N chargé pour la ville : {city}")
                else:
                    logger.warning(f"[ETL-SC] Scraping P4N a échoué pour la ville : {city}")
            except Exception as e:
                logger.error(f"[ETL-SC] Erreur lors de l'extraction/chargement P4N: {e}")

    logger.info(f"[ETL-SC] Scraping terminé pour la ville: {city}")

def main(user_role="user"):

    # 1. Import GPX (Mongo + MySQL) et récupération de la ville pour chaque fichier
    gpx_files = extract_all_gpx_files()
    if not gpx_files:
        logger.info("[ETL] Aucun fichier GPX à traiter. Arrêt du pipeline.")
        return None

    results = []
    for data, gpx_path, fname in gpx_files:
        verifie = 1 if user_role == "admin" else 0
        city = load_gpx_data(data, gpx_path, verifie=verifie)
        if not city:
            logger.info(f"[ETL] Fichier {fname} ignoré (pas de ville détectée).")
            continue
        logger.info(f"[ETL] Ville extraite du GPX: {city}")

        # 2. Extraction et chargement météo pour la ville (rapide)
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

        # 3. Lancer le scraping en arrière-plan (non bloquant)
        logger.info(f"[ETL_SC] Lancement du scraping en arrière-plan pour la ville: {city}")
        threading.Thread(target=scraping_background, args=(city,), daemon=True).start()
        results.append(city)

    # Retourner la liste des villes traitées
    logger.info(f"[ETL] Pipeline principal terminé. Villes traitées: {results}")
    return results


if __name__ == "__main__":
    main()
