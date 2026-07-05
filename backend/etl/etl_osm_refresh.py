"""
Script ponctuel : ré-extrait OSM pour toutes les villes déjà importées, afin
de récupérer les POI essentiels (eau potable, toilettes, douches, vidange
camping-car) ignorés jusqu'ici par le filtre 'name' trop strict et la requête
Overpass incomplète (voir transform_osm.py / api_osm.py).
load_osm_poi fait un INSERT IGNORE sur (original_id, source_id) : ré-exécuter
ce script est sans risque, il n'ajoute que les POI absents jusqu'ici.
"""
import time

from utils.db_utils import get_all_city_ids
from utils.logger_util import LoggerUtil
from etl.extract.api_osm import extract_osm
from etl.transform.transform_osm import transform_osm
from etl.load.load_poi import load_osm_poi

logger = LoggerUtil.get_logger("etl_osm_refresh")

# Pause entre deux villes pour rester sous la limite de requêtes Overpass
# (sans ça, les 40 appels consécutifs déclenchent des 429 en rafale).
DELAY_BETWEEN_CITIES_S = 5


def main():
    cities = get_all_city_ids()
    logger.info(f"[refresh] {len(cities)} ville(s) à retraiter")

    for i, (city_id, city_name) in enumerate(cities):
        logger.info(f"[refresh] OSM pour city_id={city_id} ({city_name})")
        try:
            osm_json = extract_osm(city_name)
            if not osm_json:
                logger.warning(f"[refresh] Pas de données OSM pour {city_name}")
            else:
                df_osm = transform_osm(osm_json, city=city_name)
                load_osm_poi(df_osm, city_name=city_name)
        except Exception as e:
            logger.error(f"[refresh] Échec pour {city_name}: {e}")

        if i < len(cities) - 1:
            time.sleep(DELAY_BETWEEN_CITIES_S)


if __name__ == "__main__":
    main()
