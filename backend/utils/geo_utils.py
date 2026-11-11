import re
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError
import logging
from math import radians, cos, sin, asin, sqrt

import requests

from utils.db_utils import MySQLUtils

logger = logging.getLogger(__name__)

def haversine_distance_km(lat1, lon1, lat2, lon2):
    """
    Calcule la distance en km entre deux points (latitude, longitude) via la formule de Haversine.
    """
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    earth_radius_km = 6371
    return 2 * earth_radius_km * asin(sqrt(a))

def distance_to_trace_km(latitude, longitude, trace):
    """
    Distance en km d'un point au tracé d'une rando (liste de points (latitude,
    longitude)) : celle du point du tracé le plus proche. None sans tracé.
    """
    if not trace:
        return None
    return min(haversine_distance_km(latitude, longitude, lat, lon) for lat, lon in trace)


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

def get_coordinates_for_city(city_name, department=None, country="France", timeout=10, max_retries=3):
    """
    Géocodage direct: obtient la latitude et la longitude d'une ville.
    Permet de préciser le département pour éviter les ambiguïtés.
    Timeout et retry custom.
    """
    from time import sleep
    query = city_name
    if department:
        query += f", {department}"
    query += f", {country}"
    for attempt in range(max_retries):
        try:
            geolocator = Nominatim(user_agent="randovango-geocoder-v1", timeout=timeout)
            location = geolocator.geocode(query)
            if location:
                logger.info(f"Coordonnées trouvées pour {query}: {location.latitude}, {location.longitude}")
                return location.latitude, location.longitude
            else:
                logger.warning(f"Aucune coordonnée trouvée pour {query}")
                return None, None
        except (GeocoderTimedOut, GeocoderServiceError) as e:
            logger.error(f"Erreur de géocodage pour {query} (tentative {attempt+1}/{max_retries}): {e}")
            sleep(2)
    return None, None


def get_city_center(city_name):
    """
    Centre de recherche d'une ville : ses coordonnées de la table `cities`, connues
    grâce au GPX. Le nom seul ne suffit pas : Saint-Philibert (Morbihan), géocodée
    par son nom, donne l'homonyme de Côte-d'Or. Géocodage seulement si elle n'y est pas.
    """
    conn = MySQLUtils.connect()
    cursor = MySQLUtils.get_cursor(conn)
    cursor.execute("SELECT latitude, longitude FROM cities WHERE name = %s ORDER BY id LIMIT 1", (city_name,))
    row = cursor.fetchone()
    cursor.close()
    MySQLUtils.disconnect(conn)
    if row:
        return row[0], row[1]
    return get_coordinates_for_city(city_name)


def get_address_from_coordinates(latitude, longitude, language='fr', timeout=10, max_retries=3):
    """
    Géocodage inversé: compose une adresse lisible ("12 Rue de la Mairie, 29880
    Plouguerneau") à partir de coordonnées GPS via Nominatim.
    Timeout et retry custom.
    """
    from time import sleep
    for attempt in range(max_retries):
        try:
            geolocator = Nominatim(user_agent="randovango-geocoder-v1", timeout=timeout)
            location = geolocator.reverse(f"{latitude}, {longitude}", language=language)

            if location and location.raw.get('address'):
                address = location.raw['address']
                road = address.get('road') or address.get('pedestrian')
                house_number = address.get('house_number')
                postcode = address.get('postcode')
                city = (address.get('city') or
                        address.get('town') or
                        address.get('village') or
                        address.get('municipality') or
                        address.get('hamlet'))

                if not road:
                    logger.warning(f"Pas de rue dans l'adresse pour ({latitude}, {longitude})")
                    return None

                street_part = f"{house_number} {road}" if house_number else road
                locality_part = f"{postcode} {city}" if postcode and city else (postcode or city or '')
                return f"{street_part}, {locality_part}" if locality_part else street_part
            else:
                logger.warning(f"Aucun résultat d'adresse pour les coordonnées ({latitude}, {longitude})")
                return None
        except (GeocoderTimedOut, GeocoderServiceError) as e:
            logger.error(f"Erreur de géocodage d'adresse pour ({latitude}, {longitude}) (tentative {attempt+1}/{max_retries}): {e}")
            sleep(2)
    return None


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

COMMUNE_URL = "https://geo.api.gouv.fr/communes"


def get_commune_from_coordinates(latitude, longitude, timeout=10):
    """
    La commune officielle qui contient ce point, d'après le découpage de l'État (geo.api.gouv.fr, gratuit) :
    (nom, code INSEE). Nominatim donne le lieu le plus proche, parfois un village : Trézien pour la pointe de
    Corsen, qui est en Plouarzel. Renvoie (None, None) si l'API ne répond pas : on ne bloque jamais l'appelant.
    """
    try:
        response = requests.get(COMMUNE_URL, params={"lat": latitude, "lon": longitude, "fields": "nom,code"},
                                timeout=timeout, headers={"User-Agent": "randovango"})
        response.raise_for_status()
        rows = response.json()
    except (requests.RequestException, ValueError) as e:
        logger.warning(f"geo.api.gouv.fr injoignable pour ({latitude}, {longitude}) : {e}")
        return None, None
    if not rows:
        logger.warning(f"Aucune commune française pour ({latitude}, {longitude})")
        return None, None
    return rows[0]["nom"], rows[0]["code"]


def city_commune(city: dict) -> str:
    """La commune d'une ville de la table cities, sinon son nom tant que la commune n'est pas connue."""
    return city.get("commune") or city["name"]


BAN_URL = "https://api-adresse.data.gouv.fr/search/"
BAN_MIN_SCORE = 0.5


def geocode_address_ban(address, latitude=None, longitude=None, timeout=5, min_score=BAN_MIN_SCORE):
    """
    Géocodage d'une adresse postale française par la Base Adresse Nationale
    (api-adresse.data.gouv.fr, publique et gratuite), précise au numéro de rue.
    Le point (latitude, longitude), s'il est donné, départage les rues homonymes.
    Renvoie (latitude, longitude), ou None si l'adresse n'est pas reconnue au
    moins à la rue ou si l'API ne répond pas (on ne bloque jamais l'appelant).
    """
    params = {"q": address, "limit": 1}
    if latitude is not None and longitude is not None:
        params |= {"lat": latitude, "lon": longitude}
    try:
        response = requests.get(BAN_URL, params=params, timeout=timeout)
        response.raise_for_status()
        features = response.json().get("features") or []
    except (requests.RequestException, ValueError) as e:
        logger.warning(f"BAN injoignable pour « {address} » : {e}")
        return None
    if not features:
        return None
    properties = features[0]["properties"]
    if properties.get("type") not in ("housenumber", "street") or properties.get("score", 0) < min_score:
        return None
    found_longitude, found_latitude = features[0]["geometry"]["coordinates"]
    return found_latitude, found_longitude


if __name__ == "__main__":
    # Exemple : Brest, 10 km
    # lat, lon, dist = 48.3904, -4.4861, 10
    lat, lon, dist = 43.2747, 5.44028, 10
    bbox = get_bounding_box(lat, lon, dist)
    print(f"BBOX pour ({lat}, {lon}) sur {dist} km : {bbox}")

LOCALITY_MIN_SCORE = 0.9


def geocode_locality_ban(address, latitude=None, longitude=None, timeout=5):
    """
    Le lieu-dit d'une adresse de campagne (« Lieu-dit Le Lannou, 29217 Plougonvelin ») par la Base Adresse Nationale :
    le centre du hameau, assez précis pour une ferme ou une crêperie isolée. À part de geocode_address_ban, qui reste
    précise à la rue pour les spots : seuls les lieux des agents s'en servent, et seulement en second essai (7 novembre
    2026 : la Biscuiterie de la Pointe Saint-Mathieu et le Potager de Saint-Mathieu restaient « position introuvable »).
    Renvoie (latitude, longitude), ou None si la BAN ne trouve pas un lieu-dit avec un score d'au moins 0,9.
    """
    # « Lieu-dit Le Lannou » fait chuter le score de la BAN : le mot n'appartient pas au nom du lieu-dit.
    query = re.sub(r"^\s*(lieu[- ]?dit|ld)\s+", "", address, flags=re.I)
    params = {"q": query, "limit": 1, "type": "locality"}
    if latitude is not None and longitude is not None:
        params |= {"lat": latitude, "lon": longitude}
    try:
        response = requests.get(BAN_URL, params=params, timeout=timeout)
        response.raise_for_status()
        features = response.json().get("features") or []
    except (requests.RequestException, ValueError) as e:
        logger.warning(f"BAN injoignable pour « {address} » : {e}")
        return None
    if not features or features[0]["properties"].get("score", 0) < LOCALITY_MIN_SCORE:
        return None
    found_longitude, found_latitude = features[0]["geometry"]["coordinates"]
    return found_latitude, found_longitude


SURE_SCORE = 0.8
WAY_WORDS = ("rue", "avenue", "boulevard", "route", "chemin", "impasse", "allee", "allée", "place", "quai", "square")


def geocode_sure_address_ban(address, latitude=None, longitude=None, timeout=5):
    """
    La même recherche que geocode_address_ban, mais gardée seulement si la Base Adresse est sûre d'elle (score d'au moins
    0,8). Pour un deuxième essai sur une adresse raccourcie : entre 0,5 et 0,6, elle rend une autre rue (« Halles
    Saint-Martin » -> « rue des Halles Saint-Louis », « Front de mer » -> « rue de Coat-Mez », essai du 11 novembre 2026).
    """
    return geocode_address_ban(address, latitude, longitude, timeout, min_score=SURE_SCORE)


def geocode_way_ban(address, latitude=None, longitude=None, timeout=5):
    """
    Une rue que la Base Adresse range parmi les lieux-dits : « 6 rue Jacques Rueff, 56000 Vannes » revient en « locality »
    nommée « Rue Jacques Rueff », score 0,83, et était refusée (Les Gaillards et Tablapizza, restés « position
    introuvable », 11 novembre 2026). Acceptée seulement si l'adresse commence par un numéro, si le lieu-dit rendu porte un
    nom de rue, et si le score atteint SURE_SCORE.
    """
    if not re.match(r"\s*\d", address or ""):
        return None
    params = {"q": address, "limit": 1}
    if latitude is not None and longitude is not None:
        params |= {"lat": latitude, "lon": longitude}
    try:
        response = requests.get(BAN_URL, params=params, timeout=timeout)
        response.raise_for_status()
        features = response.json().get("features") or []
    except (requests.RequestException, ValueError) as e:
        logger.warning(f"BAN injoignable pour « {address} » : {e}")
        return None
    if not features:
        return None
    properties = features[0]["properties"]
    name = (properties.get("name") or "").strip().lower()
    if properties.get("type") != "locality" or properties.get("score", 0) < SURE_SCORE or not name.startswith(WAY_WORDS):
        return None
    found_longitude, found_latitude = features[0]["geometry"]["coordinates"]
    return found_latitude, found_longitude
