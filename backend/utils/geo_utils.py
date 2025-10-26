"""
Utilitaires de géocodage (direct et inversé) utilisant Nominatim (OpenStreetMap).
"""
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError
import logging

logger = logging.getLogger(__name__)

def get_coordinates_for_city(city_name, country="France"):
    """
    Géocodage direct: obtient la latitude et la longitude d'une ville.
    """
    try:
        geolocator = Nominatim(user_agent="randovango-geocoder-v1")
        location = geolocator.geocode(f"{city_name}, {country}")
        
        if location:
            logger.info(f"Coordonnées trouvées pour {city_name}: {location.latitude}, {location.longitude}")
            return location.latitude, location.longitude
        else:
            logger.warning(f"Aucune coordonnée trouvée pour {city_name}")
            return None, None
            
    except (GeocoderTimedOut, GeocoderServiceError) as e:
        logger.error(f"Erreur de géocodage pour {city_name}: {e}")
        return None, None


def get_city_from_coordinates(latitude, longitude, language='fr'):
    """
    Géocodage inversé: obtient le nom de la ville à partir de coordonnées GPS.
    """
    try:
        geolocator = Nominatim(user_agent="randovango-geocoder-v1")
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
        logger.error(f"Erreur de géocodage inversé pour ({latitude}, {longitude}): {e}")
        return None
