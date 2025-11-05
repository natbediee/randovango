from utils.db_utils import MySQLUtils
from utils.logger_util import LoggerUtil
from utils.db_utils import get_all_city_ids, get_histo_poi_city_ids, get_histo_scrap_city_ids
from etl.extract.api_osm import extract_osm
from etl.extract.api_wikidata import extract_wikidata
from etl.extract.scraper_p4n import run_p4n_scraper
from etl.transform.transform_osm import transform_osm
from etl.transform.transform_wikidata import transform_wikidata
from etl.transform.transform_p4n import transform_p4n
from etl.load.load_poi import load_osm_poi, load_wikidata_poi
from etl.load.load_p4n import load_p4n_to_mysql


logger = LoggerUtil.get_logger("etl_rattrapage")

def add_fictive_histo_scrap(city_id):
    conn = MySQLUtils.connect()
    cursor = conn.cursor()
    # Ajoute une ligne fictive (spot_id=-1)
    cursor.execute("INSERT IGNORE INTO histo_scrap (spot_id, city_id, scraped_at) VALUES (-1, %s, NOW())", (city_id,))
    conn.commit()
    logger.info(f"[SCRAP] Résultat INSERT IGNORE histo_scrap city_id={city_id} : rowcount={cursor.rowcount}")
    cursor.close()
    MySQLUtils.disconnect(conn)
    logger.info(f"[SCRAP] Ajout fictif dans histo_scrap pour city_id={city_id}")

def main():
    # get_all_city_ids retourne maintenant une liste de tuples (id, name)
    all_cities = get_all_city_ids()  # [(id, name), ...]
    all_city_ids = set(city_id for city_id, _ in all_cities)
    logger.info(f"[ETL] Villes à traiter : {len(all_city_ids)}")
    histo_poi_city_ids = set(get_histo_poi_city_ids())
    logger.info(f"[POI] Villes dans histo_poi : {len(histo_poi_city_ids)}")
    histo_scrap_city_ids = set(get_histo_scrap_city_ids())
    logger.info(f"[SCRAP] Villes dans histo_scrap : {len(histo_scrap_city_ids)}")

    # Rattrapage OSM + Wiki (si city_id absent de histo_poi)
    missing_poi = all_city_ids - histo_poi_city_ids
    logger.info(f"[POI] Villes à rattraper pour OSM/Wiki : {len(missing_poi)}")
    for city_id, city_name in all_cities:
        if city_id in missing_poi:
            logger.info(f"[POI] OSM/Wiki pour city_id={city_id} ({city_name})")
            # Extraction OSM
            osm_json = extract_osm(city_name)
            if osm_json:
                df_osm = transform_osm(osm_json, city=city_name)
                load_osm_poi(df_osm, city_name=city_name)
            # Extraction Wikidata
            wikidata_json = extract_wikidata(city_name)
            if wikidata_json:
                df_wiki = transform_wikidata(wikidata_json, city_name=city_name)
                load_wikidata_poi(df_wiki, city_name=city_name)

    # Rattrapage P4N (si city_id absent de histo_scrap)
    missing_scrap = all_city_ids - histo_scrap_city_ids
    for city_id, city_name in all_cities:
        # initialiser la variable par itération pour éviter UnboundLocalError
        df_p4n = None
        if city_id in missing_scrap:
            logger.info(f"[SCRAP] P4N pour city_id={city_id} ({city_name})")
            try:
                df_p4n = run_p4n_scraper(city_name, is_headless=True, save_csv=False)
            except Exception as e:
                logger.error(f"[SCRAP][ERROR] Scraper P4N échoué pour {city_name}: {e}")
                df_p4n = None

        if df_p4n is not None and not df_p4n.empty:
            try:
                df_transformed = transform_p4n(df_p4n)
                load_p4n_to_mysql(df_transformed, city_name)
            except Exception as e:
                logger.error(f"[SCRAP] Transformation/chargement P4N échoué pour {city_name}: {e}")
        elif city_id in missing_scrap:
            add_fictive_histo_scrap(city_id)

if __name__ == "__main__":
    main()
