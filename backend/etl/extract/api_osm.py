import requests
import json
import time

from utils.logger_util import LoggerUtil
from utils.geo_utils import get_coordinates_for_city

OVERPASS_HEADERS = {
    "User-Agent": "RandoVanGo-ETL/1.0 (https://github.com/natbediee/randovango)"
}
OVERPASS_SERVERS = ("https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter")
OVERPASS_BATCH = 400           # une requête par 400 identifiants : au-delà, 504 systématique
OVERPASS_MIN_BATCH = 25
OVERPASS_ATTEMPTS = 3
OVERPASS_RETRY_SECONDS = 30
OVERPASS_PAUSE_SECONDS = 5


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
    latitude, longitude = get_coordinates_for_city(city_normalized)
    
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
    # Récupère un large éventail de POI, le filtrage se fera en transformation
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
                    nwr["amenity"="shelter"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
                    nwr["amenity"="parking"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
                    nwr["amenity"="restaurant"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
                    nwr["amenity"="cafe"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
                    nwr["amenity"="pharmacy"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
                    nwr["tourism"="camp_site"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
                    nwr["tourism"="caravan_site"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
                    nwr["tourism"="information"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
                    nwr["shop"="supermarket"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
                    nwr["shop"="convenience"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
                    nwr["shop"="bakery"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
                    nwr["amenity"="fuel"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
                    nwr["amenity"="shower"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
                    nwr["amenity"="sanitary_dump_station"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
                    nwr["amenity"="waste_disposal"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
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
    
    # Liste de serveurs Overpass à essayer (en cas d'échec du premier)
    # lz4.overpass-api.de retiré : injoignable de façon répétée (connexion impossible,
    # pas juste un 429), il ne fait que ralentir le fallback pour rien.
    overpass_servers = [
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
    ]
    
    # 2. Essayer chaque serveur jusqu'à obtenir une réponse valide
    response_data = None
    last_error = None
    
    for server_url in overpass_servers:
        # Sur 429 (trop de requêtes), on retente le même serveur après une pause
        # au lieu de l'abandonner immédiatement (limite imposée par Overpass).
        for attempt in range(2):
            try:
                logger.info(f"[Extract] : Tentative de connexion au serveur : {server_url}")
                response = requests.post(
                    server_url, data={"data": overpass_query}, headers=OVERPASS_HEADERS, timeout=90
                )

                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 10))
                    last_error = f"[Extract] : 429 Too Many Requests pour {server_url}"
                    if attempt == 0:
                        logger.warning(f"{last_error}, nouvelle tentative dans {retry_after}s...")
                        time.sleep(retry_after)
                        continue
                    logger.warning(last_error)
                    break

                response.raise_for_status()
                response_data = response.json()

                # Vérifier si la réponse contient des éléments
                elements = response_data.get('elements', [])
                logger.info(f"[Extract] : Nombre d'éléments trouvés : {len(elements)}")

                if len(elements) == 0:
                    logger.warning(f"[Extract] : Aucun élément trouvé pour '{city}' avec le serveur {server_url}")
                    # On continue avec ce résultat même s'il est vide
                else:
                    logger.info(f"[Extract] : Succès : {len(elements)} POI trouvés pour '{city}'")
                break

            except requests.exceptions.Timeout:
                last_error = f"[Extract] : Timeout pour le serveur {server_url}"
                logger.warning(last_error)
                break
            except requests.exceptions.RequestException as e:
                last_error = f"[Extract] : Erreur de connexion au serveur {server_url} : {e}"
                logger.warning(last_error)
                break
            except json.JSONDecodeError as e:
                last_error = f"[Extract] : Erreur de décodage JSON depuis {server_url} : {e}"
                logger.warning(last_error)
                break

        if response_data is not None:
            break
    
    # Si aucun serveur n'a fonctionné
    if response_data is None:
        logger.error(f"[Extract] : ÉCHEC DE L'EXTRACTION OSM : Tous les serveurs ont échoué. Dernière erreur : {last_error}")
        return None
    logger.info(f"[Extract] : Données OSM extraites pour {city_normalized} ({len(response_data.get('elements', []))} POI)")
    return response_data


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

