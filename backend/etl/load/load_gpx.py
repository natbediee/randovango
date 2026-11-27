import os
from pathlib import Path

from utils.mongo_utils import MongoUtils
from utils.logger_util import LoggerUtil
from utils.service_utils import ServiceUtil
from utils.db_utils import MySQLUtils
from utils.geo_utils import get_admin_info_from_coordinates, get_commune_details
from etl.extract.gpx import remove_file

ROOT = Path(__file__).resolve().parents[3]
logger = LoggerUtil.get_logger("etl_gpx")

ServiceUtil.load_env()

def find_city(cursor, city_name, insee):
    """
    La ville de ce nom dans cette commune. Le nom seul confondrait deux homonymes (Saint-Philibert, Morbihan et
    Côte-d'Or) ; une ville sans code (commune pas encore connue) reste reconnue à son nom.
    """
    if not insee:
        cursor.execute("SELECT id FROM cities WHERE name = %s ORDER BY id LIMIT 1", (city_name,))
    else:
        cursor.execute("SELECT id FROM cities WHERE name = %s AND (insee = %s OR insee IS NULL)"
                       " ORDER BY insee IS NULL, id LIMIT 1", (city_name, insee))
    row = cursor.fetchone()
    return row[0] if row else None


def find_admin_info(insee, latitude, longitude, details=None) -> tuple:
    """
    (département, région, pays) de la ville d'une rando qui part de ce point.
    D'abord geo.api.gouv.fr, par le code INSEE de la commune : gratuit, officiel, et il supporte un envoi de 70 villes
    d'un coup. Avant l'issue #318, ils venaient de Nominatim, qui a refusé la plupart des appels de l'import du
    23 novembre 2026 (« trop d'appels ») : 51 villes sont restées sans département, et l'agent des services cherchait
    « Champagne, France ». Nominatim ne sert plus que sans code INSEE : un départ hors de France, ou l'État injoignable.
    `details` : la commune telle que l'État l'a donnée à la lecture du GPX (transform_gpx, issue #328), avec son
    département et sa région ; sans eux, la commune est redemandée ici.
    """
    if not (details and details.get("department")) and insee:
        details = get_commune_details(insee)
    if details:
        return details["department"], details["region"], "France"
    return get_admin_info_from_coordinates(latitude, longitude)


def load_gpx_data(data, gpx_path, verifie=0) -> str:
    """
    Charge les données GPX transformées dans MongoDB et MySQL, puis retire le fichier du dossier d'attente.
    Retourne le nom de la ville, ou None si le tracé est déjà dans MongoDB (le fichier est alors retiré aussi :
    sinon il repasserait à chaque envoi, issue #266).
    verifie: 1 si admin, 0 sinon
    """
    # try/finally : la connexion MySQL se ferme même en cas d'erreur (issue #206). Pas d'open_cursor ici :
    # le chargement ouvre lui-même plusieurs curseurs successifs sur cette même connexion.
    mysql_conn = MySQLUtils.connect()
    try:
        return _load_gpx_with_connection(mysql_conn, data, gpx_path, verifie)
    finally:
        MySQLUtils.disconnect(mysql_conn)


def _load_gpx_with_connection(mysql_conn, data, gpx_path, verifie) -> str:
    """Le chargement lui-même, sur une connexion MySQL ouverte et fermée par load_gpx_data."""
    fname = os.path.basename(gpx_path)
    MongoUtils.connect()
    gpx_collection = MongoUtils.get_collection("gpx_traces")
    existing = gpx_collection.find_one({"filename": fname})
    city_name = data.get('city_name')
    if existing:
        # Avant l'issue #266, ce cas répondait par la ville, comme un succès : la page annonçait un tracé jamais chargé.
        logger.info(f"[load] : Le fichier {fname} existe déjà dans MongoDB (id={existing.get('_id')}). Ignorer l'import.")
        remove_file(gpx_path)
        return None

    logger.info(f"[load] : Import du fichier GPX: {fname}")

    start_lat = data['start_lat']
    start_lon = data['start_lon']
    description = data['description']
    # city_name déjà défini ci-dessus
    commune, insee = data.get('commune'), data.get('insee')
    cursor = mysql_conn.cursor()
    city_id = find_city(cursor, city_name, insee)
    if city_id:
        logger.info(f"[load] : Ville {city_name} trouvée avec ID={city_id}")
        if insee:
            # Une ville d'avant la colonne insee reçoit sa commune au passage.
            cursor.execute("UPDATE cities SET commune = %s, insee = %s WHERE id = %s AND insee IS NULL", (commune, insee, city_id))
            mysql_conn.commit()
    else:
        department, region, country = find_admin_info(insee, start_lat, start_lon, data.get('commune_details'))
        cursor.execute(
            "INSERT INTO cities (name, latitude, longitude, department, region, country, commune, insee)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (city_name, start_lat, start_lon, department, region, country, commune, insee)
        )
        mysql_conn.commit()
        city_id = cursor.lastrowid
        logger.info(f"[load] : Ville {city_name} ({commune or 'commune inconnue'}) créée avec ID={city_id}, {department}, {region}, {country}")
    cursor.close()

    # --- Gestion de la source ---
    source_name = data.get('author') or 'inconnue'
    with mysql_conn.cursor() as cursor:
        cursor.execute("SELECT id FROM sources WHERE name = %s", (source_name,))
        result = cursor.fetchone()
        if result:
            source_id = result[0]
        else:
            cursor.execute("INSERT INTO sources (name) VALUES (%s)", (source_name,))
            mysql_conn.commit()
            source_id = cursor.lastrowid


    # --- Insertion MySQL d'abord (mongo_id=None) ---
    cursor = mysql_conn.cursor()
    cursor.execute(
        """INSERT INTO hikes 
           (name, description, start_latitude, start_longitude, distance_km, estimated_duration_h, elevation_gain_m, difficulte, mongo_id, source_id, city_id, filename, verifie) 
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (data['name'], description, start_lat, start_lon, data['distance_km'], data['estimated_duration_h'], data['denivele_m'], data['difficulte'], None, source_id, city_id, fname, verifie)
    )
    mysql_conn.commit()
    gpxtrace_id = cursor.lastrowid



    # --- Lecture du contenu GPX brut ---
    with open(gpx_path, 'r', encoding='utf-8') as f:
        gpx_content = f.read()

    # --- Insertion MongoDB avec le contenu brut ---
    trace_doc = {
        "name": data['name'],
        "points": data['points'],
        "waypoints": data['waypoints'],
        "filename": fname,
        "hike_mysql_id": gpxtrace_id,
        "gpx_content": gpx_content
    }
    mongo_result = gpx_collection.insert_one(trace_doc)
    id_mongo = str(mongo_result.inserted_id)
    logger.info(f"[load] : Document MongoDB créé avec l'id: {id_mongo}")

    # --- Mise à jour du champ mongo_id dans MySQL ---
    cursor.execute(
        "UPDATE hikes SET mongo_id = %s WHERE id = %s",
        (id_mongo, gpxtrace_id)
    )
    mysql_conn.commit()
    cursor.close()
    logger.info(f"[load] : Loaded: {fname} (MySQL id={gpxtrace_id}, Mongo id={id_mongo})")

    # --- Suppression du fichier source après traitement ---
    remove_file(gpx_path)

    return city_name if city_name else None



