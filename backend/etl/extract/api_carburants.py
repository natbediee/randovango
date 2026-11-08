"""
Les deux sources des stations-service : le fichier de l'État et les stations d'OSM.

LE FICHIER DE L'ÉTAT (prix-carburants.gouv.fr, Licence Ouverte Etalab 2.0)
Il n'y a pas d'API : un ZIP contenant un XML de toute la France (environ 10 000 stations, 1 Mo compressé),
refait toutes les dix minutes. On prend le flux « instantané avec ruptures ». Le télécharger une fois par passage
suffit, quel que soit le nombre de villes : le tri par ville est fait ensuite (transform_carburants.keep_near).
Le fichier ne donne ni le nom ni la marque des stations.

OSM
On demande les stations-service autour de la ville, avec toutes leurs étiquettes : beaucoup portent
ref:FR:prix-carburants, l'identifiant de l'État, qui donne la marque sans deviner. L'ETL OSM des services
(api_osm.extract_osm) ne garde pas cette étiquette : cette requête est faite à part, pour ne pas le modifier.
"""
import io
import zipfile

import requests

from etl.extract.api_osm import _query_with_backoff
from utils.geo_utils import get_bounding_box
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


def extract_osm_fuel(latitude: float, longitude: float, distance_km: float, label: str) -> list | None:
    """Les stations-service OSM du carré autour du point, avec leurs étiquettes. None si Overpass ne répond pas."""
    south, west, north, east = get_bounding_box(latitude, longitude, distance_km)
    query = f'[out:json][timeout:60];nwr["amenity"="fuel"]({south},{west},{north},{east});out tags center;'
    data = _query_with_backoff(query, label)
    if data is None:
        return None
    return data.get("elements", [])
