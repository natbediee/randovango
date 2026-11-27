import os
from pathlib import Path

from bson import ObjectId

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


def trace_already_loaded(mysql_conn, gpx_collection, fname) -> bool:
    """
    Dit si le tracé de ce fichier est déjà en base avec sa rando. Un tracé resté seul, sans rando (un enregistrement
    annulé dont MongoDB n'a pas pu retirer le tracé, issue #285), ne bloque pas un nouvel envoi : il est retiré ici,
    et le fichier se charge normalement.
    """
    existing = gpx_collection.find_one({"filename": fname})
    if not existing:
        return False
    with mysql_conn.cursor() as cursor:
        cursor.execute("SELECT 1 FROM hikes WHERE filename = %s LIMIT 1", (fname,))
        hike_found = cursor.fetchone() is not None
    if hike_found:
        logger.info(f"[load] : Le fichier {fname} existe déjà dans MongoDB (id={existing.get('_id')}). Ignorer l'import.")
        return True
    logger.warning(f"[load] : Tracé {existing.get('_id')} de {fname} resté sans rando : retiré avant le nouvel envoi")
    gpx_collection.delete_many({"filename": fname})
    return False


def load_gpx_data(data, gpx_path, verifie=0) -> str:
    """
    Charge les données GPX transformées dans MongoDB et MySQL, puis retire le fichier du dossier d'attente.
    Retourne le nom de la ville, ou None si la rando et son tracé sont déjà en base (le fichier est alors retiré aussi :
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
    city_name = data.get('city_name')
    if trace_already_loaded(mysql_conn, gpx_collection, fname):
        # Avant l'issue #266, ce cas répondait par la ville, comme un succès : la page annonçait un tracé jamais chargé.
        remove_file(gpx_path)
        return None

    logger.info(f"[load] : Import du fichier GPX: {fname}")

    start_lat = data['start_lat']
    start_lon = data['start_lon']
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


    # La rando et son tracé, ensemble ou pas du tout (issue #285).
    save_hike_with_trace(mysql_conn, gpx_collection, data, gpx_path, source_id, city_id, verifie)

    # --- Suppression du fichier source après traitement ---
    remove_file(gpx_path)

    return city_name if city_name else None


# POURQUOI CES FONCTIONS (issue #285)
# Une rando vit à deux endroits : sa fiche dans MySQL (table hikes) et son tracé dans MongoDB (gpx_traces), reliés
# par hikes.mongo_id. Avant l'issue #285, la rando était validée dans MySQL avant l'écriture du tracé : si MongoDB
# échouait entre les deux (conteneur arrêté, connexion coupée, document de plus de 16 Mo), la rando restait sans
# tracé, et un nouvel envoi du même fichier était refusé comme « déjà en base ».
# La règle est maintenant « tout ou rien » : la rando n'est validée dans MySQL (commit) qu'une fois son tracé écrit.
# Si quelque chose échoue, la rando est annulée (rollback) et le tracé déjà écrit est retiré.
# La ville et la source, elles, restent validées : ce sont des données de référence, reprises au prochain envoi.

def save_hike_with_trace(mysql_conn, gpx_collection, data, gpx_path, source_id, city_id, verifie) -> None:
    """
    Enregistre la rando dans MySQL et son tracé dans MongoDB, ensemble ou pas du tout. En cas d'échec, rien ne reste
    ni d'un côté ni de l'autre, et l'erreur continue son chemin : l'envoi répond par un échec, et le même fichier peut
    être renvoyé.
    """
    fname = os.path.basename(gpx_path)
    trace_id = None
    try:
        with mysql_conn.cursor() as cursor:
            # La rando d'abord, sans commit : MySQL donne son id, que le tracé garde (hike_mysql_id).
            hike_id = insert_hike(cursor, data, fname, source_id, city_id, verifie)
            trace_id = insert_trace(gpx_collection, data, gpx_path, hike_id)
            cursor.execute("UPDATE hikes SET mongo_id = %s WHERE id = %s", (trace_id, hike_id))
        # Le commit seulement maintenant : la rando n'existe en base qu'avec son tracé.
        mysql_conn.commit()
    except Exception:
        mysql_conn.rollback()
        if trace_id:
            remove_trace(gpx_collection, trace_id)
        raise
    logger.info(f"[load] : Loaded: {fname} (MySQL id={hike_id}, Mongo id={trace_id})")


def insert_hike(cursor, data, fname, source_id, city_id, verifie) -> int:
    """Écrit la fiche de la rando dans hikes, sans tracé encore (mongo_id vide), sans commit, et rend son id."""
    cursor.execute(
        """INSERT INTO hikes
           (name, description, start_latitude, start_longitude, distance_km, estimated_duration_h, elevation_gain_m, difficulte, mongo_id, source_id, city_id, filename, verifie)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (data['name'], data['description'], data['start_lat'], data['start_lon'], data['distance_km'],
         data['estimated_duration_h'], data['denivele_m'], data['difficulte'], None, source_id, city_id, fname, verifie)
    )
    return cursor.lastrowid


def insert_trace(gpx_collection, data, gpx_path, hike_id) -> str:
    """Écrit le tracé de la rando dans MongoDB, avec le contenu brut du fichier GPX, et rend l'id du document."""
    with open(gpx_path, 'r', encoding='utf-8') as f:
        gpx_content = f.read()
    trace_doc = {
        "name": data['name'],
        "points": data['points'],
        "waypoints": data['waypoints'],
        "filename": os.path.basename(gpx_path),
        "hike_mysql_id": hike_id,
        "gpx_content": gpx_content
    }
    trace_id = str(gpx_collection.insert_one(trace_doc).inserted_id)
    logger.info(f"[load] : Document MongoDB créé avec l'id: {trace_id}")
    return trace_id


def remove_trace(gpx_collection, trace_id) -> None:
    """
    Retire le tracé d'une rando annulée. Si MongoDB ne répond plus, le tracé reste sans rando : on le note dans les
    logs, et le prochain envoi du même fichier le remplacera (trace_already_loaded).
    """
    try:
        gpx_collection.delete_one({"_id": ObjectId(trace_id)})
        logger.info(f"[load] : Tracé {trace_id} retiré, sa rando n'a pas pu être enregistrée")
    except Exception as e:
        logger.error(f"[load] : Tracé {trace_id} resté sans rando, MongoDB n'a pas pu le retirer : {e}")


def delete_hike_with_trace(filename) -> tuple:
    """
    Retire une rando et son tracé, ensemble ou pas du tout, et rend (randos retirées, tracés retirés).
    La rando n'est retirée de MySQL (commit) qu'une fois son tracé retiré de MongoDB : si MongoDB échoue, la rando
    reste avec son tracé. Si MySQL refuse (la rando est dans un voyage), rien n'est touché.
    """
    with MySQLUtils.open_cursor() as (mysql_conn, cursor):
        cursor.execute("DELETE FROM hikes WHERE filename = %s", (filename,))
        hikes_deleted = cursor.rowcount
        try:
            MongoUtils.connect()
            traces_deleted = MongoUtils.get_collection("gpx_traces").delete_many({"filename": filename}).deleted_count
        except Exception:
            mysql_conn.rollback()
            raise
        mysql_conn.commit()
    return hikes_deleted, traces_deleted
