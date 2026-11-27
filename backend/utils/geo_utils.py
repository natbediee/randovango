import re
import time
import unicodedata
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
    # « with » : la connexion se ferme à la sortie du bloc, même en cas d'erreur (issue #206).
    with MySQLUtils.open_cursor() as (conn, cursor):
        cursor.execute("SELECT latitude, longitude FROM cities WHERE name = %s ORDER BY id LIMIT 1", (city_name,))
        row = cursor.fetchone()
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

# LES ESSAIS (issue #318) : le 23 novembre 2026, 70 villes sont arrivées d'un coup, et geo.api.gouv.fr n'a pas répondu
# à temps pour La Jonchère. Sans nouvel essai, la ville est restée sans commune. Trois essais, une pause qui s'allonge.
GEO_API_ATTEMPTS = 3
GEO_API_PAUSE_SECONDS = 2


def get_geo_api(url, params, timeout):
    """
    Une demande à geo.api.gouv.fr, réessayée GEO_API_ATTEMPTS fois si l'API ne répond pas ou répond une erreur
    (trop d'appels à la fois, serveur occupé). Renvoie la réponse lue (JSON), ou lève la dernière erreur.
    """
    for attempt in range(1, GEO_API_ATTEMPTS + 1):
        try:
            response = requests.get(url, params=params, timeout=timeout, headers={"User-Agent": "randovango"})
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            if attempt == GEO_API_ATTEMPTS:
                raise
            logger.warning(f"geo.api.gouv.fr, essai {attempt}/{GEO_API_ATTEMPTS} sans réponse : {e}")
            time.sleep(GEO_API_PAUSE_SECONDS * attempt)


def get_commune_at(latitude, longitude, timeout=10) -> dict | None:
    """
    La commune officielle qui contient ce point, d'après le découpage de l'État (geo.api.gouv.fr, gratuit), avec ce
    qu'il faut pour créer sa ville : {"name", "insee", "department", "region"}. None si le point n'est dans aucune
    commune française, ou si l'API ne répond pas, même après ses essais : on ne bloque jamais l'appelant.
    Le département et la région viennent dans la même réponse (issue #328) : une ville nouvelle d'un envoi n'a plus
    besoin d'une seconde demande à l'État, et un envoi de 240 randos fait 240 demandes au lieu de 400.
    """
    params = {"lat": latitude, "lon": longitude, "fields": "nom,code,departement,region"}
    try:
        rows = get_geo_api(COMMUNE_URL, params, timeout)
    except (requests.RequestException, ValueError) as e:
        logger.warning(f"geo.api.gouv.fr injoignable pour ({latitude}, {longitude}) : {e}")
        return None
    if not rows:
        logger.warning(f"Aucune commune française pour ({latitude}, {longitude})")
        return None
    row = rows[0]
    # Une commune d'outre-mer ou une réponse partielle peut venir sans département ni région : on garde la commune.
    return {"name": row["nom"], "insee": row["code"],
            "department": (row.get("departement") or {}).get("nom"), "region": (row.get("region") or {}).get("nom")}


def get_commune_from_coordinates(latitude, longitude, timeout=10):
    """
    La commune officielle qui contient ce point (get_commune_at), en (nom, code INSEE). Nominatim donne le lieu le plus
    proche, parfois un village : Trézien pour la pointe de Corsen, qui est en Plouarzel. (None, None) si l'API ne
    répond pas ou si le point n'est dans aucune commune.
    """
    commune = get_commune_at(latitude, longitude, timeout)
    if commune is None:
        return None, None
    return commune["name"], commune["insee"]


def get_commune_details(insee: str, timeout=10) -> dict | None:
    """
    Ce qu'il faut pour créer la ligne d'une commune dans cities, d'après geo.api.gouv.fr : son nom officiel, la position
    de son centre, son département et sa région. Plouguerneau, que l'appli ne connaissait que par ses lieux-dits Lilia
    et Tremenac'h (issue #184). Renvoie None si l'API ne répond pas, même après ses essais.
    """
    try:
        row = get_geo_api(f"{COMMUNE_URL}/{insee}", {"fields": "nom,code,centre,departement,region"}, timeout)
    except (requests.RequestException, ValueError) as e:
        logger.warning(f"geo.api.gouv.fr injoignable pour la commune {insee} : {e}")
        return None
    # GeoJSON écrit la longitude d'abord : [-4.5104, 48.6046].
    longitude, latitude = row["centre"]["coordinates"]
    return {"name": row["nom"], "insee": row["code"], "latitude": latitude, "longitude": longitude,
            "department": row["departement"]["nom"], "region": row["region"]["nom"]}


# LA COMMUNE D'UNE ADRESSE (supervision, 8 et 12 novembre 2026) : ce qui suit le code postal, « 29730 Guilvinec ».
# Un service se range par la commune de son adresse, même quand ce n'est pas une ville de l'appli (le Carrefour de
# Guilvinec) : c'est aussi ce qu'un voyageur donnera en signalant un service.
ADDRESS_TOWN = re.compile(r"\b(\d{5})\s+([^,]+?)\s*$")


def address_town(address: str | None) -> str | None:
    """La commune d'une adresse « Quai Neuf, 29680 Roscoff » : ce qui suit le code postal."""
    match = ADDRESS_TOWN.search(address or "")
    return match.group(2) if match else None


def town_key(town: str | None) -> str:
    """« Île-de-Batz », « ile de batz » et « ILE-DE-BATZ » sont la même commune."""
    plain = unicodedata.normalize("NFKD", town or "").encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[-'’]", " ", plain).lower().split())


def town_choices(addresses: list, cities: list) -> tuple:
    """
    Ce que la recherche de ville de la supervision propose, tiré des adresses :
        ({city["id"]: [codes postaux]} des villes de l'appli (cities : id, name, commune facultative),
         [{"nom": « Guilvinec », "codes": ["29730"]}] des communes qui ne sont pas des villes de l'appli, triées).
    Les codes postaux permettent de chercher « 29730 ».
    """
    city_of = {town_key(name): city["id"] for city in cities for name in (city["name"], city_commune(city))}
    city_codes, towns = {}, {}
    for address in addresses:
        match = ADDRESS_TOWN.search(address or "")
        if not match:
            continue
        code, town = match.groups()
        key = town_key(town)
        if key in city_of:
            city_codes.setdefault(city_of[key], set()).add(code)
        else:
            towns.setdefault(key, {"nom": town, "codes": set()})["codes"].add(code)
    return ({city_id: sorted(codes) for city_id, codes in city_codes.items()},
            [{"nom": town["nom"], "codes": sorted(town["codes"])} for _, town in sorted(towns.items())])


def city_commune(city: dict) -> str:
    """La commune d'une ville de la table cities, sinon son nom tant que la commune n'est pas connue."""
    return city.get("commune") or city["name"]


def communes_only(alias: str = "") -> str:
    """
    Le filtre SQL qui ne garde que les communes de la table cities, pas les lieux-dits (issue #184, décision du
    15 novembre 2026). Une ville vient du départ d'une rando : parfois un lieu-dit (Lochrist, au Conquet ; Lilia et
    Tremenac'h, en Plouguerneau). Une commune est une ligne dont le nom est celui de sa commune ; celles qui
    manquaient ont été créées par etl/add_missing_communes.py. Les lieux-dits restent en base pour les anciens voyages.
    MySQL compare sans tenir compte de la casse ni des accents : « Plounéour-Brignogan-plages » est bien sa commune.
    Une ville dont la commune n'est pas encore connue reste gardée : on ne sait pas si c'est un lieu-dit.
    alias : la lettre de la table cities dans une jointure (« c »), pour ne pas confondre avec un autre « name ».
    """
    prefix = f"{alias}." if alias else ""
    return f"({prefix}commune IS NULL OR {prefix}name = {prefix}commune)"


# Les randos rangées dans une ville de la même commune (même code INSEE, donné en paramètre %s) : la rando d'un lieu-dit
# reste proposée depuis sa commune, même quand elle part loin de son centre (Locuon et Ploërdut, issue #184).
# Une commune encore inconnue (insee vide) ne retrouve rien par ce chemin : « insee = NULL » n'est jamais vrai en SQL.
SAME_COMMUNE_HIKES = "city_id IN (SELECT id FROM cities WHERE insee = %s)"


# LE LIEU-DIT DEVIENT SA COMMUNE (issue #184, étape 2). Une adresse venue d'un agent, d'OSM ou de la source des spots
# finit parfois par un lieu-dit : « 29810 Trézien » au lieu de « 29810 Plouarzel ». Tout le code lit la commune après
# le code postal (address_town) : la supervision rangeait alors le service sous « Trézien », et l'étape 4 ne le voyait
# pas depuis Plouarzel. L'adresse est réécrite à la façon de La Poste, le lieu-dit sur sa propre ligne :
# « rue, Trézien, 29810 Plouarzel ». Seul l'État sait quelles communes porte un code postal : geo.api.gouv.fr.
POSTCODE_COMMUNES = {}      # {code postal : [noms officiels de ses communes]}, gardé pour ne demander qu'une fois


def communes_of_postcode(postcode: str, timeout=10) -> list:
    """
    Les noms officiels des communes d'un code postal (29810 : Brélès, Lampaul-Plouarzel, Plouarzel, Ploumoguer).
    Liste vide si l'API ne répond pas ; seule une réponse est gardée, pour réessayer la fois suivante.
    """
    if postcode in POSTCODE_COMMUNES:
        return POSTCODE_COMMUNES[postcode]
    try:
        response = requests.get(COMMUNE_URL, params={"codePostal": postcode, "fields": "nom,code"},
                                timeout=timeout, headers={"User-Agent": "randovango"})
        response.raise_for_status()
        names = [row["nom"] for row in response.json()]
    except (requests.RequestException, ValueError) as e:
        logger.warning(f"geo.api.gouv.fr injoignable pour le code postal {postcode} : {e}")
        return []
    POSTCODE_COMMUNES[postcode] = names
    return names


def spelling_key(town: str | None) -> str:
    """La clé d'un nom sans casse, accents, traits d'union, apostrophes ni espaces : « Penmarc'h » donne « penmarch »."""
    return town_key(town).replace(" ", "")


def same_spelling(town: str, commune: str) -> bool:
    """« Penmarc'h » et « Penmarch », « PLOUDALMEZEAU » et « Ploudalmézeau » : le même nom autrement écrit."""
    return spelling_key(town) == spelling_key(commune)


TOWN_IS_COMMUNE = {}        # {clé d'un nom : est-ce une commune de France ?}, gardé pour ne demander qu'une fois
LOCALITY_COMMUNES = None    # {clé d'un lieu-dit de la table cities : sa commune}, lu une fois dans la base


def known_locality_commune(town: str) -> str | None:
    """
    La commune d'un lieu-dit que la table cities connaît déjà (Trézien : Plouarzel ; Lochrist : Le Conquet). C'est
    la réponse sûre pour les points que l'État ne place dans aucune commune : un sentier côtier, une cale, posés un peu
    en mer (la reprise du 15 novembre 2026 en laissait 66, tous sur l'un de ces lieux-dits, dont 10 à Trézien).
    """
    global LOCALITY_COMMUNES
    if LOCALITY_COMMUNES is None:
        with MySQLUtils.open_cursor() as (connection, cursor):
            cursor.execute("SELECT name, commune FROM cities WHERE commune IS NOT NULL AND name <> commune")
            LOCALITY_COMMUNES = {spelling_key(name): commune for name, commune in cursor.fetchall()}
    return LOCALITY_COMMUNES.get(spelling_key(town))


def is_commune_name(town: str, timeout=10) -> bool | None:
    """
    Ce nom est-il celui d'une commune de France, au besoin autrement écrit ? Séné l'est, Trézien non. None si l'API
    ne répond pas : on ne sait pas.
    """
    key = spelling_key(town)
    if key in TOWN_IS_COMMUNE:
        return TOWN_IS_COMMUNE[key]
    try:
        response = requests.get(COMMUNE_URL, params={"nom": town, "fields": "nom", "limit": 5},
                                timeout=timeout, headers={"User-Agent": "randovango"})
        response.raise_for_status()
        names = [row["nom"] for row in response.json()]
    except (requests.RequestException, ValueError) as e:
        logger.warning(f"geo.api.gouv.fr injoignable pour le nom {town} : {e}")
        return None
    TOWN_IS_COMMUNE[key] = any(same_spelling(town, name) for name in names)
    return TOWN_IS_COMMUNE[key]


def commune_of_town(postcode: str, town: str, latitude=None, longitude=None) -> str | None:
    """
    Le nom officiel de la commune où se trouve `town`, écrit après le code postal d'une adresse :
        - `town` lui-même, s'il est une commune de ce code postal (au besoin, autrement écrit) ;
        - sinon la commune connue de ce lieu-dit dans la table cities (Trézien : Plouarzel), si elle porte ce code ;
        - sinon la seule commune du code postal (29160 Morgat : Crozon et Lanvéoc, il faut la position) ;
        - sinon celle des communes du code postal qui contient la position du lieu.
    None si on ne sait pas : l'adresse est alors laissée telle quelle. C'est aussi le cas d'une vraie commune écrite
    avec le code postal d'une autre : « 56000 Séné » n'est pas un lieu-dit de Vannes, c'est le code qui est faux
    (essai de la reprise, 15 novembre 2026 : Séné, Vannes, La Feuillée, Fouesnant).
    """
    communes = communes_of_postcode(postcode)
    if not communes:
        return None
    official = next((commune for commune in communes if same_spelling(town, commune)), None)
    if official:
        return official
    # Le lieu-dit connu passe avant la vérification du nom : Argenton, lieu-dit de Landunvez (29840), est aussi le nom
    # d'une commune du Lot-et-Garonne, et ses 9 services restaient sinon à « 29840 Argenton ».
    known = known_locality_commune(town)
    if known in communes:
        return known
    if is_commune_name(town) is not False:
        return None
    if len(communes) == 1:
        return communes[0]
    if latitude is None or longitude is None:
        return None
    commune, _ = get_commune_from_coordinates(latitude, longitude)
    return commune if commune in communes else None


def address_with_commune(address: str | None, latitude=None, longitude=None) -> str | None:
    """
    L'adresse avec la commune après le code postal : « 553 Korejoù, 29880 Tremenac'h » devient « 553 Korejoù,
    Tremenac'h, 29880 Plouguerneau ». Une commune autrement écrite prend son nom officiel (« 29760 Penmarch »).
    Une adresse sans code postal, déjà juste, ou dont la commune reste inconnue, est rendue telle quelle.
    """
    match = ADDRESS_TOWN.search(address or "")
    if not match:
        return address
    postcode, town = match.groups()
    commune = commune_of_town(postcode, town, latitude, longitude)
    if commune is None or commune == town:
        return address
    street = address[:match.start()].rstrip(" ,")
    locality = "" if same_spelling(town, commune) else f"{town}, "
    return f"{street}, {locality}{postcode} {commune}" if street else f"{locality}{postcode} {commune}"


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
