import sys
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError

def get_coordinates_for_city(city_name):
    """
    Utilise l'API Nominatim (OSM) pour obtenir la latitude et la longitude d'une ville.
    """
    try:
        # Utilisation de Nominatim (OpenStreetMap)
        geolocator = Nominatim(user_agent="geocoder_scraper_api_v1")
        # On peut ajouter le pays pour une meilleure précision
        location = geolocator.geocode(city_name + ", France")
        
        if location:
            return location.latitude, location.longitude
        else:
            return None, None
            
    except (GeocoderTimedOut, GeocoderServiceError) as e:
        print(f"Erreur de géocodage: {e}")
        return None, None

# Note : Si vous exécutez ce fichier seul, il ne fera rien,
# mais il est prêt à être importé.
if __name__ == '__main__':
    if len(sys.argv) > 1:
        get_coordinates_for_city(sys.argv[1])
    else:
        print("Usage: python3 geo_utils.py Ville")