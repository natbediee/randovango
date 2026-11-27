"""
La source des prix des stations-service : le fichier de l'État.

LE FICHIER DE L'ÉTAT (prix-carburants.gouv.fr, Licence Ouverte Etalab 2.0)
Il n'y a pas d'API : un ZIP contenant un XML de toute la France (environ 10 000 stations, 1 Mo compressé),
refait toutes les dix minutes. On prend le flux « instantané avec ruptures ». Le télécharger une fois par passage
suffit, quel que soit le nombre de villes : le tri par ville est fait ensuite (transform_carburants.keep_near).
Le fichier ne donne ni le nom ni la marque des stations : ils viennent d'OSM, que l'étape OSM interroge pour la ville
(api_osm.extract_osm) et range dans osm_fuel_stations, avec l'étiquette ref:FR:prix-carburants, l'identifiant de l'État.
"""
import io
import zipfile

import requests

from utils.logger_util import LoggerUtil

logger = LoggerUtil.get_logger("etl_carburants")

STATE_FILE_URL = "https://donnees.roulez-eco.fr/opendata/instantane_ruptures"
HEADERS = {"User-Agent": "RandoVanGo-ETL/1.0 (https://github.com/natbediee/randovango)"}
TIMEOUT_SECONDS = 60


def download_state_file() -> bytes | None:
    """Le XML du fichier de l'État, décompressé. None si le site ne répond pas : le passage s'arrête sans rien écrire."""
    try:
        response = requests.get(STATE_FILE_URL, headers=HEADERS, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            xml = archive.read(archive.namelist()[0])
    except (requests.exceptions.RequestException, zipfile.BadZipFile, IndexError) as error:
        logger.error(f"[Extract] : fichier des carburants illisible : {error}")
        return None
    logger.info(f"[Extract] : fichier des carburants lu ({len(response.content) // 1024} Ko compressé)")
    return xml
