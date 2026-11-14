"""
La source des pharmacies : le registre FINESS de l'État (carte #194).

LE FICHIER
L'ancien fichier CSV de FINESS est arrêté depuis mai 2026. Le registre est publié depuis juillet 2026 sous le nom
« FINESS - Structures » sur data.gouv.fr (Licence Ouverte v2.0) : un JSON compressé de toute la France, refait chaque
jour. Son adresse change chaque jour (la date est dans le nom) : on la demande d'abord à l'API de data.gouv.fr.

LE LIRE EN FLUX
Le fichier pèse 52 Mo compressé mais 767 Mo une fois ouvert : lu d'un seul bloc, il prenait 4,5 Go de mémoire
(essai du 14 novembre 2026). ijson le lit structure par structure, sans jamais tout garder : on ne retient que les
pharmacies, environ 24 000 petites entrées.

OÙ SONT LES PHARMACIES
Le fichier liste des entités juridiques (« pmej »), chacune avec ses établissements (« ege »). Une pharmacie
est un établissement de catégorie 620.
"""
import gzip
import tempfile

import ijson
import requests

from utils.logger_util import LoggerUtil

logger = LoggerUtil.get_logger("etl_pharmacies")

DATASET_URL = "https://www.data.gouv.fr/api/1/datasets/finess-structures-1/"
DAILY_FILE_PREFIX = "finess-structures-journalier"
PHARMACY_CATEGORY = "620"
HEADERS = {"User-Agent": "RandoVanGo-ETL/1.0 (https://github.com/natbediee/randovango)"}
TIMEOUT_SECONDS = 120
CHUNK_BYTES = 1024 * 1024


def daily_file_url(dataset: dict) -> str | None:
    """L'adresse du fichier du jour parmi les fichiers du jeu de données (les autres sont les copies mensuelles)."""
    for resource in dataset.get("resources", []):
        if resource.get("title", "").startswith(DAILY_FILE_PREFIX):
            return resource.get("url")
    return None


def pharmacies_of(structure: dict) -> list:
    """Les établissements de catégorie 620 (pharmacies) d'une entité juridique du fichier."""
    return [ege for ege in structure.get("ege") or []
            if ege.get("categorieentiteGeographiqueExercice") == PHARMACY_CATEGORY]


def read_pharmacies_file(compressed_file) -> list:
    """Toutes les pharmacies d'un fichier FINESS compressé, ouvertes ou fermées, lues en flux."""
    pharmacies = []
    with gzip.open(compressed_file) as content:
        for structure in ijson.items(content, "pmej.item"):
            pharmacies.extend(pharmacies_of(structure))
    return pharmacies


def download_pharmacies() -> list | None:
    """
    Les pharmacies du fichier FINESS du jour. None si data.gouv.fr ne répond pas ou si le fichier est illisible :
    le passage s'arrête alors sans rien écrire.
    """
    try:
        dataset = requests.get(DATASET_URL, headers=HEADERS, timeout=TIMEOUT_SECONDS).json()
        url = daily_file_url(dataset)
        if url is None:
            logger.error("[Extract] : aucun fichier FINESS du jour sur data.gouv.fr")
            return None
        # Le fichier est écrit sur le disque, pas gardé en mémoire : ijson le relit ensuite morceau par morceau.
        with tempfile.TemporaryFile() as temporary, requests.get(url, headers=HEADERS, timeout=TIMEOUT_SECONDS,
                                                                 stream=True) as response:
            response.raise_for_status()
            for chunk in response.iter_content(CHUNK_BYTES):
                temporary.write(chunk)
            temporary.seek(0)
            pharmacies = read_pharmacies_file(temporary)
    except (requests.exceptions.RequestException, ValueError, OSError, ijson.JSONError) as error:
        logger.error(f"[Extract] : fichier FINESS illisible : {error}")
        return None
    logger.info(f"[Extract] : {len(pharmacies)} pharmacies lues dans FINESS ({url})")
    return pharmacies
