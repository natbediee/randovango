import requests
import json
import time

from utils.logger_util import LoggerUtil
from utils.geo_utils import get_city_center

OVERPASS_HEADERS = {
    "User-Agent": "RandoVanGo-ETL/1.0 (https://github.com/natbediee/randovango)"
}
OVERPASS_SERVERS = ("https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter")
OVERPASS_BATCH = 400           # une requête par 400 identifiants : au-delà, 504 systématique
OVERPASS_MIN_BATCH = 25
OVERPASS_ATTEMPTS = 3
OVERPASS_RETRY_SECONDS = 30
OVERPASS_PAUSE_SECONDS = 5
OVERPASS_BUSY_STATUS = {429, 500, 502, 503, 504}
OVERPASS_BACKOFF_SECONDS = (30, 60, 120)  # attentes entre deux essais de tous les serveurs
OVERPASS_MAX_RETRY_AFTER_SECONDS = 300


logger = LoggerUtil.get_logger("etl_osm")


def extract_osm(city: str) -> dict:
    """
    Récupère les POI d'OSM pour la ville donnée via l'API Overpass.
    Les données sont filtrées pour les points d'intérêt pertinents.
    Utilise une approche avec recherche par bounding box.
    """
    logger.info(f"[Extract] : Lancement de l'extraction OSM via Overpass pour '{city}'...")
    
    # Normalisation du nom de la ville
    city_normalized = city.strip()
    # 1. Obtenir les coordonnées de la ville
    logger.info(f"[Extract] : Recherche des coordonnées pour '{city_normalized}'...")
    latitude, longitude = get_city_center(city_normalized)
    
    if latitude is None or longitude is None:
        logger.error(f"[Extract] : Impossible de trouver les coordonnées pour '{city_normalized}'")
        return None

    logger.info(f"[Extract] : Coordonnées trouvées : {latitude}, {longitude}")

    # 2. Créer une bounding box autour de la ville (environ 5km de rayon)
    # Approximation : 1 degré de latitude ≈ 111 km
    # 0.05 degré ≈ 5.5 km de rayon effectif
    radius_deg = 0.05
    bbox = {
        'south': latitude - radius_deg,
        'north': latitude + radius_deg,
        'west': longitude - radius_deg,
        'east': longitude + radius_deg
    }

    logger.info(f"[Extract] : Bounding box : {bbox} (rayon ~5-6 km)")

    # 3. Requête Overpass QL utilisant la bounding box
    # Récupère un large éventail de POI, le filtrage se fera en transformation.
    # Plus d'abris, de parkings ni de poubelles (8 novembre 2026) : l'étape 4 ne les montre jamais
    # (utils/service_utils.POI_FRONTEND_CATEGORY_MAP), ils n'encombraient que la supervision (3 435 lieux, sans nom).
    # Plus de campings ni d'aires de camping-car non plus (14 novembre 2026, carte #196) : même cas, l'étape 4 ne les
    # montre jamais et les spots sont la bonne source pour dormir (228 campings et 98 aires visibles n'encombraient que la
    # supervision). Le badge « Caravaneige » des spots vient de P4N, pas d'ici : il n'est pas touché.
    overpass_query = f"""
                [out:json][timeout:45];
                (
                    nwr["tourism"="attraction"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
                    nwr["tourism"="viewpoint"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
                    nwr["man_made"="lighthouse"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
                    nwr["historic"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
                    nwr["natural"="beach"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
                    nwr["amenity"="drinking_water"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
                    nwr["amenity"="toilets"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
                    nwr["amenity"="restaurant"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
                    nwr["amenity"="cafe"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
                    nwr["amenity"="pharmacy"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
                    nwr["tourism"="information"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
                    nwr["shop"="supermarket"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
                    nwr["shop"="convenience"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
                    nwr["shop"="bakery"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
                    nwr["amenity"="fuel"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
                    nwr["amenity"="shower"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
                    nwr["amenity"="sanitary_dump_station"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
                    nwr["shop"="laundry"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
                    // Culture et loisirs : alimentent l'étape 4 et servent à retrouver
                    // la position des pépites de Vany (pepite_service.locate).
                    nwr["amenity"="cinema"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
                    nwr["amenity"="theatre"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
                    nwr["amenity"="arts_centre"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
                    nwr["amenity"="marketplace"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
                    nwr["tourism"="museum"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
                    nwr["tourism"="gallery"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
                    nwr["shop"="farm"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
                    nwr["craft"="brewery"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
                );
                out center;
        """
    logger.info(f"[Extract] : Requête Overpass envoyée : {overpass_query}")

    response_data = _query_with_backoff(overpass_query, city_normalized)
    if response_data is None:
        return None
    nb_elements = len(response_data.get("elements", []))
    if nb_elements == 0:
        logger.warning(f"[Extract] : Aucun élément trouvé pour '{city_normalized}'")
    logger.info(f"[Extract] : Données OSM extraites pour {city_normalized} ({nb_elements} POI)")
    return response_data


class OverpassBusy(Exception):
    """Serveur saturé ou muet : la même requête peut réussir un peu plus tard."""

    def __init__(self, reason: str, retry_after: int = 0):
        super().__init__(reason)
        self.retry_after = retry_after


def _retry_after_seconds(response: requests.Response) -> int:
    try:
        return int(response.headers.get("Retry-After", 0))
    except ValueError:
        return 0


def _ask_overpass(server_url: str, query: str) -> dict:
    """La réponse complète du serveur. OverpassBusy s'il faut réessayer, HTTPError si la requête est refusée."""
    try:
        response = requests.post(server_url, data={"data": query}, headers=OVERPASS_HEADERS, timeout=90)
    except requests.exceptions.RequestException as error:
        raise OverpassBusy(type(error).__name__) from error
    if response.status_code in OVERPASS_BUSY_STATUS:
        raise OverpassBusy(f"HTTP {response.status_code}", _retry_after_seconds(response))
    response.raise_for_status()
    try:
        data = response.json()
    except ValueError as error:
        raise OverpassBusy("réponse illisible") from error
    # Saturé, Overpass peut répondre 200 avec une partie des lieux et une remarque d'erreur.
    remark = data.get("remark") or ""
    if "error" in remark.lower():
        raise OverpassBusy(remark)
    return data


def _query_with_backoff(query: str, city: str) -> dict | None:
    """
    Essaie chaque serveur, attend de plus en plus longtemps, puis recommence.
    Dinard, 3 novembre 2026 : 0 lieu au premier passage, 552 deux minutes plus tard.
    Le voyageur n'attend pas : cette étape tourne dans un thread d'arrière-plan.
    """
    waits = (*OVERPASS_BACKOFF_SECONDS, None)
    for attempt, wait in enumerate(waits, start=1):
        worth_retrying, retry_after = False, 0
        for server_url in OVERPASS_SERVERS:
            try:
                logger.info(f"[Extract] : {city}, essai {attempt}/{len(waits)} sur {server_url}")
                return _ask_overpass(server_url, query)
            except OverpassBusy as busy:
                worth_retrying, retry_after = True, max(retry_after, busy.retry_after)
                logger.warning(f"[Extract] : {server_url} indisponible : {busy}")
            except requests.exceptions.HTTPError as rejected:
                logger.warning(f"[Extract] : {server_url} a refusé la requête : {rejected}")
        if not worth_retrying or wait is None:
            break
        pause = max(wait, min(retry_after, OVERPASS_MAX_RETRY_AFTER_SECONDS))
        logger.warning(f"[Extract] : {city}, nouvel essai dans {pause} s")
        time.sleep(pause)
    logger.error(f"[Extract] : ÉCHEC DE L'EXTRACTION OSM pour {city} après {attempt} essai(s)")
    return None


def extract_osm_by_ids(osm_ids: list) -> tuple:
    """
    Relit dans OSM les objets déjà connus, par identifiant. Contrairement à extract_osm,
    elle voit aussi ceux qui ne sont plus marqués comme restaurant (disused:amenity...).
    La base ne dit pas si l'identifiant est celui d'un node ou d'un way : on demande les trois.
    Un paquet qui échoue est rejoué en plus petits morceaux : un même paquet de 400 a échoué
    deux passages de suite, faisant perdre les autres.
    Renvoie ({identifiant: [éléments]}, identifiants non lus) : leur absence ne prouve rien.
    """
    by_id, unread = {}, set()
    for start in range(0, len(osm_ids), OVERPASS_BATCH):
        _read_batch(osm_ids[start:start + OVERPASS_BATCH], by_id, unread)
        logger.info(f"[Extract] : {min(start + OVERPASS_BATCH, len(osm_ids))}/{len(osm_ids)} identifiants traités")
        time.sleep(OVERPASS_PAUSE_SECONDS)
    return by_id, unread


def _read_batch(ids: list, by_id: dict, unread: set) -> None:
    joined = ",".join(ids)
    query = f"[out:json][timeout:90];(node(id:{joined});way(id:{joined});relation(id:{joined}););out tags center;"
    elements = _post_overpass_with_retry(query)
    if elements is not None:
        for element in elements:
            by_id.setdefault(str(element["id"]), []).append(element)
        return
    if len(ids) <= OVERPASS_MIN_BATCH:
        logger.warning(f"[Extract] : {len(ids)} identifiants non lus")
        unread.update(ids)
        return
    middle = len(ids) // 2
    _read_batch(ids[:middle], by_id, unread)
    _read_batch(ids[middle:], by_id, unread)


def _post_overpass_with_retry(query: str) -> list | None:
    """Overpass répond souvent 502 ou 504 : pilote sur 2 329 restaurants, 3 paquets sur 6 ont dû être rejoués."""
    for attempt in range(OVERPASS_ATTEMPTS):
        for server_url in OVERPASS_SERVERS:
            try:
                response = requests.post(server_url, data={"data": query}, headers=OVERPASS_HEADERS, timeout=120)
                if response.ok:
                    return response.json().get("elements", [])
                logger.warning(f"[Extract] : {server_url} a répondu {response.status_code}")
            except (requests.exceptions.RequestException, json.JSONDecodeError) as error:
                logger.warning(f"[Extract] : {server_url} : {type(error).__name__}")
        if attempt < OVERPASS_ATTEMPTS - 1:
            time.sleep(OVERPASS_RETRY_SECONDS)
    return None

