import requests
import json
from pathlib import Path

from utils.service_utils import ServiceUtil
from utils.logger_util import LoggerUtil
from utils.geo_utils import get_coordinates_for_city


logger = LoggerUtil.get_logger("api_osm")

# Chemin vers data/in

ROOT_PATH = Path(__file__).resolve().parents[3]
DATA_IN = ROOT_PATH / ServiceUtil.get_env("DATA_IN") / "osm"

def extract_osm(city: str) -> dict:
    """
    Récupère les POI d'OSM pour la ville donnée via l'API Overpass.
    Les données sont filtrées pour les points d'intérêt pertinents.
    Utilise une approche robuste avec recherche par bounding box.
    """
    logger.info(f"Lancement de l'extraction OSM via Overpass pour '{city}'...")
    
    # Normalisation du nom de la ville
    city_normalized = city.strip()
    # 1. Obtenir les coordonnées de la ville
    logger.info(f"Recherche des coordonnées pour '{city_normalized}'...")
    latitude, longitude = get_coordinates_for_city(city_normalized)
    
    if latitude is None or longitude is None:
        logger.error(f"Impossible de trouver les coordonnées pour '{city_normalized}'")
        return None
    
    logger.info(f"Coordonnées trouvées : {latitude}, {longitude}")
    
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
    
    logger.info(f"Bounding box : {bbox} (rayon ~5-6 km)")
    
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
        );
        out center;
    """
    
    # Liste de serveurs Overpass à essayer (en cas d'échec du premier)
    overpass_servers = [
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
        "https://lz4.overpass-api.de/api/interpreter"
    ]
    
    # 2. Essayer chaque serveur jusqu'à obtenir une réponse valide
    response_data = None
    last_error = None
    
    for server_url in overpass_servers:
        try:
            logger.info(f"Tentative de connexion au serveur : {server_url}")
            response = requests.post(server_url, data={'data': overpass_query}, timeout=90)
            response.raise_for_status()
            
            response_data = response.json()
            
            # Vérifier si la réponse contient des éléments
            elements = response_data.get('elements', [])
            logger.info(f"Nombre d'éléments trouvés : {len(elements)}")
            
            if len(elements) == 0:
                logger.warning(f"Aucun élément trouvé pour '{city}' avec le serveur {server_url}")
                # On continue avec ce résultat même s'il est vide
            else:
                logger.info(f"Succès : {len(elements)} POI trouvés pour '{city}'")
            
            # Si on arrive ici, la requête a réussi (même si vide)
            break
            
        except requests.exceptions.Timeout:
            last_error = f"Timeout pour le serveur {server_url}"
            logger.warning(last_error)
            continue
        except requests.exceptions.RequestException as e:
            last_error = f"Erreur de connexion au serveur {server_url} : {e}"
            logger.warning(last_error)
            continue
        except json.JSONDecodeError as e:
            last_error = f"Erreur de décodage JSON depuis {server_url} : {e}"
            logger.warning(last_error)
            continue
    
    # Si aucun serveur n'a fonctionné
    if response_data is None:
        logger.error(f"ÉCHEC DE L'EXTRACTION OSM : Tous les serveurs ont échoué. Dernière erreur : {last_error}")
        return None
    logger.info(f"Données OSM extraites pour {city_normalized} ({len(response_data.get('elements', []))} POI)")
    return response_data

