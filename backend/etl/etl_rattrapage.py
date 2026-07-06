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
from etl.etl_meteo import run_meteo_etl


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
    logger.info(f"[ETL] Total de villes en base : {len(all_city_ids)}")

    # Rattrapage OSM et Wikidata suivis indépendamment : une ville où une seule
    # des deux sources a réussi (ex. Wikidata OK, OSM vide/échoué) doit pouvoir
    # être retentée pour la source manquante, sans être considérée "déjà traitée".
    histo_osm_city_ids = set(get_histo_poi_city_ids('osm'))
    histo_wikidata_city_ids = set(get_histo_poi_city_ids('wikidata'))
    histo_scrap_city_ids = set(get_histo_scrap_city_ids())
    logger.info(f"[POI] Villes déjà traitées (OSM) : {len(histo_osm_city_ids)}")
    logger.info(f"[POI] Villes déjà traitées (Wikidata) : {len(histo_wikidata_city_ids)}")
    logger.info(f"[SCRAP] Villes déjà traitées (P4N déjà scrapé) : {len(histo_scrap_city_ids)}")

    missing_osm = all_city_ids - histo_osm_city_ids
    missing_wikidata = all_city_ids - histo_wikidata_city_ids
    logger.info(f"[POI] Villes restant à rattraper pour OSM : {len(missing_osm)}")
    logger.info(f"[POI] Villes restant à rattraper pour Wikidata : {len(missing_wikidata)}")

    for city_id, city_name in all_cities:
        if city_id in missing_osm:
            logger.info(f"[POI] OSM pour city_id={city_id} ({city_name})")
            try:
                osm_json = extract_osm(city_name)
                if osm_json:
                    df_osm = transform_osm(osm_json, city=city_name)
                    load_osm_poi(df_osm, city_name=city_name)
            except Exception as e:
                # Un échec sur une ville ne doit pas interrompre le rattrapage des suivantes.
                logger.error(f"[POI][OSM] Échec pour city_id={city_id} ({city_name}) : {e}")
        if city_id in missing_wikidata:
            logger.info(f"[POI] Wikidata pour city_id={city_id} ({city_name})")
            try:
                wikidata_json = extract_wikidata(city_name)
                if wikidata_json:
                    df_wiki = transform_wikidata(wikidata_json, city_name=city_name)
                    load_wikidata_poi(df_wiki, city_name=city_name)
            except Exception as e:
                logger.error(f"[POI][Wikidata] Échec pour city_id={city_id} ({city_name}) : {e}")

    # Rattrapage P4N (si city_id absent de histo_scrap)
    missing_scrap = all_city_ids - histo_scrap_city_ids
    logger.info(f"[SCRAP] Villes restant à rattraper pour P4N : {len(missing_scrap)}")
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

def rattrapage_meteo():
    """Relance l'ETL météo pour les villes sans prévisions à jour (coordonnées depuis DB, pas Nominatim)."""
    cnx = MySQLUtils.connect()
    cursor = cnx.cursor(dictionary=True)
    cursor.execute("""
        SELECT c.id, c.name, c.latitude, c.longitude
        FROM cities c
        LEFT JOIN weather w ON w.city_id = c.id AND w.date >= CURDATE()
        WHERE w.id IS NULL
        GROUP BY c.id, c.name, c.latitude, c.longitude
        ORDER BY c.name
    """)
    missing = cursor.fetchall()
    cursor.close()
    MySQLUtils.disconnect(cnx)

    logger.info(f"[METEO] Villes restant à rattraper (prévisions absentes/périmées) : {len(missing)}")
    for city in missing:
        logger.info(f"[METEO] Rattrapage pour {city['name']}")
        result = run_meteo_etl(city['name'], city['latitude'], city['longitude'])
        if 'error' in result or 'warning' in result:
            logger.warning(f"[METEO] {city['name']} : {result}")
        else:
            logger.info(f"[METEO] {city['name']} : OK")


if __name__ == "__main__":
    main()
    rattrapage_meteo()
