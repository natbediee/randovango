"""
L'étape OSM d'une ville : extraction, transformation, chargement.
Un échec n'est plus noté dans un fichier à part : l'étape passe par la chaîne « osm » des passages (issue #276), qui
garde l'échec en base avec sa raison, et la supervision le relance (services/etl_chains.py).

Les stations-service ne sont pas chargées comme services : elles sont rangées dans osm_fuel_stations, où l'étape des
carburants vient les relire. Overpass n'est donc interrogé qu'une fois par ville, ici.
"""
from datetime import datetime

from etl.extract.api_osm import extract_osm
from etl.load.load_carburants import save_osm_fuel_stations
from etl.load.load_poi import load_osm_poi
from etl.transform.transform_carburants import osm_fuel_stations
from etl.transform.transform_osm import transform_osm
from utils.logger_util import LoggerUtil

logger = LoggerUtil.get_logger("etl_osm")


def run_osm_etl(city: str) -> int | None:
    """Renvoie le nombre de lieux retenus, ou None si OSM n'a pas pu être lu."""
    osm_json = extract_osm(city)
    if osm_json is None:
        logger.error(f"[OSM] OSM en échec pour {city}")
        return None
    df_osm = transform_osm(osm_json, city=city)
    load_osm_poi(df_osm, city_name=city)
    save_osm_fuel_stations(city, osm_fuel_stations(osm_json), datetime.now().replace(microsecond=0))
    # Import ici : la règle charge les services de la supervision, inutiles pour lire ce module.
    from services import poi_duplicates_service
    poi_duplicates_service.after_load(city)
    return 0 if df_osm is None else len(df_osm)
