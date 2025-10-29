from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError
import logging
from math import radians, cos

logger = logging.getLogger(__name__)

def get_admin_info_from_coordinates(latitude, longitude, language='fr', timeout=10, max_retries=3):
    """
    Retourne (department, region, country) à partir de coordonnées GPS via Nominatim.
    Timeout et retry custom.
    """
    from time import sleep
    for attempt in range(max_retries):
        try:
            geolocator = Nominatim(user_agent="randovango-geocoder-v1", timeout=timeout)
            location = geolocator.reverse(f"{latitude}, {longitude}", language=language)
            if location and location.raw.get('address'):
                address = location.raw['address']
                department = address.get('state_district') or address.get('county')
                region = address.get('state')
                country = address.get('country')
                return department, region, country
            else:
                logger.warning(f"Aucun résultat admin pour les coordonnées ({latitude}, {longitude})")
                return None, None, None
        except (GeocoderTimedOut, GeocoderServiceError) as e:
            logger.error(f"Erreur admin geocoding pour ({latitude}, {longitude}) (tentative {attempt+1}/{max_retries}): {e}")
            sleep(2)
    return None, None, None

def get_bounding_box(latitude, longitude, distance_km):
    """
    Calcule une bounding box autour d'un point (latitude, longitude) pour une distance donnée (en km).
    Retourne (min_lat, min_lon, max_lat, max_lon)
    """
    # Rayon de la Terre en km
    lat = radians(latitude)
    # Latitude min/max
    min_lat = latitude - (distance_km / 111.32)
    max_lat = latitude + (distance_km / 111.32)
    # Longitude min/max (corrigé par la latitude)
    delta_lon = distance_km / (111.32 * cos(lat))
    min_lon = longitude - delta_lon
    max_lon = longitude + delta_lon
    return min_lat, min_lon, max_lat, max_lon

def get_coordinates_for_city(city_name, country="France", timeout=10, max_retries=3):
    """
    Géocodage direct: obtient la latitude et la longitude d'une ville.
    Timeout et retry custom.
    """
    from time import sleep
    for attempt in range(max_retries):
        try:
            geolocator = Nominatim(user_agent="randovango-geocoder-v1", timeout=timeout)
            location = geolocator.geocode(f"{city_name}, {country}")
            if location:
                logger.info(f"Coordonnées trouvées pour {city_name}: {location.latitude}, {location.longitude}")
                return location.latitude, location.longitude
            else:
                logger.warning(f"Aucune coordonnée trouvée pour {city_name}")
                return None, None
        except (GeocoderTimedOut, GeocoderServiceError) as e:
            logger.error(f"Erreur de géocodage pour {city_name} (tentative {attempt+1}/{max_retries}): {e}")
            sleep(2)
    return None, None


def get_city_from_coordinates(latitude, longitude, language='fr', timeout=10, max_retries=3):
    """
    Géocodage inversé: obtient le nom de la ville à partir de coordonnées GPS.
    Timeout et retry custom.
    """
    from time import sleep
    for attempt in range(max_retries):
        try:
            geolocator = Nominatim(user_agent="randovango-geocoder-v1", timeout=timeout)
            location = geolocator.reverse(f"{latitude}, {longitude}", language=language)
            
            if location and location.raw.get('address'):
                address = location.raw['address']
                # Essayer différents niveaux de localité (du plus spécifique au plus général)
                city = (address.get('city') or 
                       address.get('town') or 
                       address.get('village') or 
                       address.get('municipality') or
                       address.get('hamlet'))
                
                if city:
                    logger.info(f"Ville trouvée pour ({latitude}, {longitude}): {city}")
                    return city
                else:
                    logger.warning(f"Aucune ville trouvée dans l'adresse pour ({latitude}, {longitude})")
                    return None
            else:
                logger.warning(f"Aucun résultat pour les coordonnées ({latitude}, {longitude})")
                return None
        except (GeocoderTimedOut, GeocoderServiceError) as e:
            logger.error(f"Erreur de géocodage inversé pour ({latitude}, {longitude}) (tentative {attempt+1}/{max_retries}): {e}")
            sleep(2)
    return None
