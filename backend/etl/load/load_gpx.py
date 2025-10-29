import os
from pathlib import Path

from utils.mongo_utils import MongoUtils
from utils.logger_util import LoggerUtil
from utils.service_utils import ServiceUtil
from utils.mysql_utils import MySQLUtils
from utils.geo_utils import get_admin_info_from_coordinates

ROOT = Path(__file__).resolve().parents[3]
logger = LoggerUtil.get_logger("load_gpx")

ServiceUtil.load_env()
mysql_conn = MySQLUtils.connect()

def load_gpx_data(data, gpx_path, verifie=0) -> str:
    """
    Charge les données GPX transformées dans MongoDB et MySQL, puis archive le fichier.
    Retourne le nom de la ville ou None si déjà importé.
    verifie: 1 si admin, 0 sinon
    """
    fname = os.path.basename(gpx_path)
    MongoUtils.connect()
    gpx_collection = MongoUtils.get_collection("gpx_traces")
    existing = gpx_collection.find_one({"filename": fname})
    city_name = data.get('city_name')
    if existing:
        logger.info(f"Le fichier {fname} existe déjà dans MongoDB (id={existing.get('_id')}). Ignorer l'import.")
        print(f"Le fichier {fname} a déjà été importé.")
        return city_name if city_name else None

    logger.info(f"Import du fichier GPX: {fname}")

    start_lat = data['start_lat']
    start_lon = data['start_lon']
    description = data['description']
    # city_name déjà défini ci-dessus
    cursor = mysql_conn.cursor()
    cursor.execute("SELECT id FROM cities WHERE name = %s", (city_name,))
    result = cursor.fetchone()
    if result:
        city_id = result[0]
        logger.info(f"Ville {city_name} trouvée avec ID={city_id}")
    else:
        # Récupérer infos admin
        department, region, country = get_admin_info_from_coordinates(start_lat, start_lon)
        cursor.execute(
            "INSERT INTO cities (name, latitude, longitude, department, region, country) VALUES (%s, %s, %s, %s, %s, %s)",
            (city_name, start_lat, start_lon, department, region, country)
        )
        mysql_conn.commit()
        city_id = cursor.lastrowid
        logger.info(f"Ville {city_name} créée avec ID={city_id}, {department}, {region}, {country}")
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
           (name, description, start_latitude, start_longitude, distance_km, estimated_duration_h, elevation_gain_m, mongo_id, source_id, city_id, filename, verifie) 
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (data['name'], description, start_lat, start_lon, data['distance_km'], data['estimated_duration_h'], data['denivele_m'], None, source_id, city_id, fname, verifie)
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
    logger.info(f"Document MongoDB créé avec l'id: {id_mongo}")

    # --- Mise à jour du champ mongo_id dans MySQL ---
    cursor.execute(
        "UPDATE hikes SET mongo_id = %s WHERE id = %s",
        (id_mongo, gpxtrace_id)
    )
    mysql_conn.commit()
    cursor.close()
    logger.info(f'Loaded: {fname} (MySQL id={gpxtrace_id}, Mongo id={id_mongo})')
    print(f'Loaded: {fname} (MySQL id={gpxtrace_id}, Mongo id={id_mongo})')

    # --- Suppression du fichier source après traitement ---
    try:
        os.remove(gpx_path)
        logger.info(f"Fichier supprimé : {gpx_path}")
        print(f"Fichier supprimé : {gpx_path}")
    except Exception as e:
        logger.warning(f"Erreur lors de la suppression du fichier {gpx_path} : {e}")

    return city_name if city_name else None


if __name__ == '__main__':
    print("Ce module fournit load_gpx_data pour charger les données GPX transformées.")
