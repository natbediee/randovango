import os
import logging
import mysql.connector
import gpxpy
from pathlib import Path
from backend.services.service_mongo import ServiceMongo
from backend.utils.service_util import ServiceUtil
from backend.utils.geo_utils import get_city_from_coordinates

# Configuration du logging pour GPX
ROOT = Path(__file__).resolve().parents[3]
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Ajouter un handler pour le fichier gpx.log
gpx_log_handler = logging.FileHandler(ROOT / "logs/gpx.log", mode='a', encoding='utf-8')
gpx_log_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(gpx_log_handler)

ServiceUtil.load_env()
mysql_conn = mysql.connector.connect(
    host=ServiceUtil.get_env('DB_HOST', 'localhost'),
    user=ServiceUtil.get_env('DB_USER', 'root'),
    password=ServiceUtil.get_env('DB_PSWD', 'motdepasse'),
    database=ServiceUtil.get_env('DB_NAME', 'randovango'),
    charset='utf8mb4'
)
ServiceMongo.connect()

INPUT = ServiceUtil.get_env('DATA_GPX', 'data/in/gpx')

def load_gpx():
    """
    Charge un fichier GPX dans MongoDB et MySQL.
    Vérifie si le fichier existe déjà avant insertion.
    """
    # Vérifie et ajoute le champ 'filename' dans la table MySQL 'hikes' si besoin
    cursor = mysql_conn.cursor()
    cursor.execute("SHOW COLUMNS FROM hikes LIKE 'filename'")
    result = cursor.fetchone()
    if not result:
        cursor.execute("ALTER TABLE hikes ADD COLUMN filename VARCHAR(255)")
        mysql_conn.commit()
    
    # On ne traite qu'un seul fichier GPX dans le dossier
    gpx_files = [f for f in os.listdir(INPUT) if f.endswith('.gpx')]
    if not gpx_files:
        logger.warning("Aucun fichier GPX trouvé dans le dossier.")
        return None
    
    fname = gpx_files[0]
    gpx_path = os.path.join(INPUT, fname)
    
    # Vérifier si le fichier existe déjà dans MongoDB
    gpx_collection = ServiceMongo.get_collection("gpx_traces")
    existing = gpx_collection.find_one({"filename": fname})
    
    if existing:
        logger.info(f"Le fichier {fname} existe déjà dans MongoDB (id={existing.get('_id')}). Ignorer l'import.")
        print(f"Le fichier {fname} a déjà été importé.")
        return None
    
    logger.info(f"Import du fichier GPX: {fname}")
    
    # Parse le fichier GPX avec gpxpy
    with open(gpx_path, 'r') as gpx_file:
        gpx = gpxpy.parse(gpx_file)
    
    # Extraction des données du GPX
    points = []
    waypoints = []
    distance_km = 0
    denivele_m = 0
    start_lat = None
    start_lon = None
    description = None
    
    # Extraire la description du GPX
    if gpx.description:
        description = gpx.description
    elif gpx.tracks and gpx.tracks[0].description:
        description = gpx.tracks[0].description
    
    for track in gpx.tracks:
        for segment in track.segments:
            for i, point in enumerate(segment.points):
                # Capturer le premier point comme point de départ
                if i == 0 and start_lat is None:
                    start_lat = point.latitude
                    start_lon = point.longitude
                
                points.append({
                    'lat': point.latitude,
                    'lon': point.longitude,
                    'ele': point.elevation
                })
    
    for waypoint in gpx.waypoints:
        waypoints.append({
            'name': waypoint.name,
            'lat': waypoint.latitude,
            'lon': waypoint.longitude,
            'ele': waypoint.elevation,
            'desc': waypoint.description
        })
    
    # Calcul de la distance et du dénivelé
    if gpx.tracks:
        # Calcul de la distance en 3D (incluant l'altitude)
        total_distance = 0
        for track in gpx.tracks:
            track_distance = track.length_3d()
            if track_distance:
                total_distance += track_distance
        distance_km = total_distance / 1000 if total_distance else 0
        
        # Calcul du dénivelé positif (montée) - méthode manuelle
        total_uphill = 0
        total_downhill = 0
        
        for track in gpx.tracks:
            for segment in track.segments:
                previous_elevation = None
                for point in segment.points:
                    if point.elevation is not None:
                        if previous_elevation is not None:
                            elevation_diff = point.elevation - previous_elevation
                            if elevation_diff > 0:
                                total_uphill += elevation_diff
                            else:
                                total_downhill += abs(elevation_diff)
                        previous_elevation = point.elevation
        
        denivele_m = total_uphill
        
        # Arrondir distance au km supérieur et dénivelé sans décimale
        import math
        distance_km_rounded = math.ceil(distance_km)  # Arrondi au km supérieur
        denivele_m_rounded = round(denivele_m)  # Arrondi sans décimale
        
        # Calcul de la durée estimée (formule de Naismith)
        # Vitesse base: 4 km/h en terrain plat
        # Ajout: 1h pour 600m de dénivelé positif
        time_distance_h = distance_km / 4  # Temps basé sur la distance
        time_elevation_h = denivele_m / 600  # Temps supplémentaire pour le dénivelé
        estimated_duration_h = round(time_distance_h + time_elevation_h)  # Total arrondi à l'heure
        
        logger.info(f"Distance: {distance_km:.2f} km → {distance_km_rounded} km (arrondi)")
        logger.info(f"Dénivelé positif: {denivele_m:.0f} m → {denivele_m_rounded} m (arrondi)")
        logger.info(f"Dénivelé négatif: {total_downhill:.0f} m")
        logger.info(f"Durée estimée: {estimated_duration_h} h (arrondi)")
    else:
        logger.warning("Aucun track trouvé dans le GPX, distance et dénivelé = 0")
        distance_km_rounded = 0
        denivele_m_rounded = 0
        estimated_duration_h = 0
    
    # Extraction du nom depuis le GPX ou depuis le nom du fichier
    hike_name = None
    if gpx.tracks and gpx.tracks[0].name:
        hike_name = gpx.tracks[0].name
    else:
        # Utilise le nom du fichier sans extension comme fallback
        hike_name = os.path.splitext(fname)[0]
    
    # Création de l'objet data (utiliser les valeurs arrondies pour MySQL)
    data = {
        'name': hike_name,
        'distance_km': distance_km_rounded,
        'denivele_m': denivele_m_rounded,
        'estimated_duration_h': estimated_duration_h,
        'points': points,
        'waypoints': waypoints,
        'author': gpx.author_name if gpx.author_name else 'inconnue'
    }
    # Extraire la ville à partir des coordonnées de départ
    city_name = None
    city_id = None
    if start_lat and start_lon:
        city_name = get_city_from_coordinates(start_lat, start_lon, language='fr')
        if city_name:
            logger.info(f"Ville détectée: {city_name}")
            # Créer ou récupérer l'ID de la ville
            cursor = mysql_conn.cursor()
            cursor.execute("SELECT id FROM cities WHERE name = %s", (city_name,))
            result = cursor.fetchone()
            if result:
                city_id = result[0]
                logger.info(f"Ville {city_name} trouvée avec ID={city_id}")
            else:
                # Créer la ville avec les coordonnées
                cursor.execute(
                    "INSERT INTO cities (name, latitude, longitude) VALUES (%s, %s, %s)",
                    (city_name, start_lat, start_lon)
                )
                mysql_conn.commit()
                city_id = cursor.lastrowid
                logger.info(f"Ville {city_name} créée avec ID={city_id}")
            cursor.close()
        else:
            logger.warning("Impossible de déterminer la ville depuis les coordonnées")
    
    # Détermine la source à partir du champ 'author' dans le GPX (métadonnée GPX)
    source_name = data.get('author') or 'inconnue'
    # Gestion de la source : vérifie si elle existe, sinon crée
    with mysql_conn.cursor() as cursor:
        cursor.execute("SELECT id FROM sources WHERE name = %s", (source_name,))
        result = cursor.fetchone()
        if result:
            source_id = result[0]
        else:
            cursor.execute("INSERT INTO sources (name) VALUES (%s)", (source_name,))
            mysql_conn.commit()
            source_id = cursor.lastrowid
    # Insert MongoDB via ServiceMongo
    trace_doc = {
        "name": data['name'],
        "distance_km": data['distance_km'],
        "denivele_m": data['denivele_m'],
        "points": data['points'],
        "waypoints": data['waypoints'],
        "filename": fname,
        "description": description
    }
    gpx_collection = ServiceMongo.get_collection("gpx_traces")
    mongo_result = gpx_collection.insert_one(trace_doc)
    id_mongo = str(mongo_result.inserted_id)
    
    logger.info(f"Document MongoDB créé avec l'id: {id_mongo}")
    
    # Insert MySQL avec id_mongo, source_id, city_id, filename, description, coordonnées de départ et durée estimée
    cursor = mysql_conn.cursor()
    cursor.execute(
        """INSERT INTO hikes 
           (name, description, start_latitude, start_longitude, distance_km, estimated_duration_h, elevation_gain_m, mongo_id, source_id, city_id, filename) 
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (data['name'], description, start_lat, start_lon, data['distance_km'], data['estimated_duration_h'], data['denivele_m'], id_mongo, source_id, city_id, fname)
    )
    mysql_conn.commit()
    gpxtrace_id = cursor.lastrowid
    
    # Mise à jour du document MongoDB avec l'id MySQL
    gpx_collection.update_one({"_id": mongo_result.inserted_id}, {"$set": {"gpxtrace_id": gpxtrace_id}})
    
    logger.info(f'Loaded: {fname} (MySQL id={gpxtrace_id}, Mongo id={id_mongo})')
    print(f'Loaded: {fname} (MySQL id={gpxtrace_id}, Mongo id={id_mongo})')
    
    # Déplacer le fichier vers archive/gpx après traitement réussi
    import shutil
    archive_dir = os.path.join(ROOT, 'data', 'archive', 'gpx')
    os.makedirs(archive_dir, exist_ok=True)  # Créer le dossier s'il n'existe pas
    
    archive_path = os.path.join(archive_dir, fname)
    shutil.move(gpx_path, archive_path)
    logger.info(f"Fichier déplacé vers: {archive_path}")
    print(f"Fichier déplacé vers archive: {archive_path}")
    
    # Retourner le nom de la ville pour l'utiliser dans le reste du pipeline
    return city_name if city_name else "Plougonvelin"

def get_city_from_gpx(gpx_path):
    """
    Extrait le nom de la ville depuis un fichier GPX.
    Utilise le point de départ du GPX pour faire un géocodage inversé.
    """
    with open(gpx_path, 'r') as gpx_file:
        gpx = gpxpy.parse(gpx_file)
    
    # Récupérer le premier point du premier track
    if gpx.tracks and gpx.tracks[0].segments and gpx.tracks[0].segments[0].points:
        first_point = gpx.tracks[0].segments[0].points[0]
        lat = first_point.latitude
        lon = first_point.longitude
        
        # Géocodage inversé pour trouver la ville
        city = get_city_from_coordinates(lat, lon, language='fr')
        if city:
            return city
    
    # Fallback: retourner "Plougonvelin" par défaut
    print(f"Impossible de déterminer la ville depuis {gpx_path}, utilisation du fallback")
    return "Plougonvelin"

if __name__ == '__main__':
    load_gpx()
