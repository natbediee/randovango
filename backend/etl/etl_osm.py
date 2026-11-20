"""
L'étape OSM d'une ville : extraction, transformation, chargement.
Un échec n'est plus noté dans un fichier à part : l'étape passe par la chaîne « osm » des passages (issue #276), qui
garde l'échec en base avec sa raison, et la supervision le relance (services/etl_chains.py).
"""
from etl.extract.api_osm import extract_osm
from etl.load.load_poi import load_osm_poi
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
    # Import ici : la règle charge les services de la supervision, inutiles pour lire ce module.
    from services import poi_duplicates_service
    poi_duplicates_service.after_load(city)
    return 0 if df_osm is None else len(df_osm)
