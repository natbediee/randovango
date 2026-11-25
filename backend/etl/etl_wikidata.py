"""
L'étape Wikidata d'une ville : extraction, transformation, chargement des lieux connus de Wikidata (forts, phares...).

Elle passe à la fin de la partie OSM de la chaîne « osm » (services/etl_chains.py, issue #316) : avant, elle tournait
dans le fil de fond de chaque rando, hors de la file des passages. Elle reste juste après OSM, comme avant : un lieu de
Wikidata est souvent déjà venu d'OSM (Fort Montbarey, Tour Vauban), et la règle des doublons a besoin des deux.
"""
from etl.extract.api_wikidata import extract_wikidata
from etl.load.load_poi import load_wikidata_poi
from etl.transform.transform_wikidata import transform_wikidata
from utils.logger_util import LoggerUtil

logger = LoggerUtil.get_logger("etl_wikidata")


def run_wikidata_etl(city: str) -> int | None:
    """
    Charge les lieux de Wikidata autour de la ville, puis repasse la règle des doublons ; rend leur nombre, ou None si
    Wikidata n'a pas pu être lu. Ne lève jamais : Wikidata est un plus, son échec ne fait pas échouer OSM.
    """
    try:
        wikidata_json = extract_wikidata(city)
        df_wiki = transform_wikidata(wikidata_json=wikidata_json, city_name=city)
        load_wikidata_poi(df_wiki=df_wiki, city_name=city)
        # Import ici : la règle charge les services de la supervision, inutiles pour lire ce module.
        from services import poi_duplicates_service
        poi_duplicates_service.after_load(city)
    except Exception as error:
        logger.error(f"[Wikidata] Wikidata en échec pour {city} : {error}")
        return None
    count = 0 if df_wiki is None else len(df_wiki)
    logger.info(f"[Wikidata] {count} lieux chargés pour {city}")
    return count
