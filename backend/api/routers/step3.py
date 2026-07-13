from fastapi import APIRouter, Query, Body
from services.plan_service import insert_or_update_plan
from utils.display_utils import enrich_spot
from utils.logger_util import LoggerUtil
from utils.db_utils import MySQLUtils

router = APIRouter()
logger = LoggerUtil.get_logger(__name__)

@router.get("/spots", summary="Returns the spots for a given city.")
def get_spots(
    city_id: int = Query(..., description="ID de la ville"),
    distance_km: float = Query(5, description="Rayon de la zone en km")
):
    """
    Retourne les spots (bivouac, camping, aire CC) pour une ville donnée,
    vérifiés ou non, quel que soit le statut de connexion de l'utilisateur.
    """
    logger.info(f"Route /spots appelée avec city_id={city_id}, distance_km={distance_km}")

    # Connexion DB
    from utils.geo_utils import get_bounding_box
    cnx = MySQLUtils.connect()
    cursor = cnx.cursor(dictionary=True)

    # Récupérer les coordonnées de la ville
    cursor.execute("SELECT latitude, longitude FROM cities WHERE id = %s", (city_id,))
    city = cursor.fetchone()
    if not city:
        cursor.close()
        MySQLUtils.disconnect(cnx)
        return []

    min_lat, min_lon, max_lat, max_lon = get_bounding_box(city['latitude'], city['longitude'], distance_km)
    
    cnx = MySQLUtils.connect()
    cursor = cnx.cursor(dictionary=True)

    # Récupérer les spots dans la bounding box (vérifiés et non vérifiés)
    excluded_types = ('AIRE DE SERVICES SANS STAT.', "SERVICES D'APPOINT")

    query = '''
            SELECT s.id, s.name, s.description, s.type, s.latitude, s.longitude, s.rating, s.url, s.verifie, s.address
            FROM spots s
            WHERE s.latitude BETWEEN %s AND %s
                AND s.longitude BETWEEN %s AND %s
                AND s.type IS NOT NULL
                AND s.type NOT IN (%s, %s)
            ORDER BY s.name ASC
        '''
    cursor.execute(query, (min_lat, max_lat, min_lon, max_lon, *excluded_types))
    spots = cursor.fetchall()

    # Récupérer les services associés à chaque spot
    spot_ids = [spot["id"] for spot in spots]
    services_map = {}
    if spot_ids:
        format_strings = ','.join(['%s'] * len(spot_ids))
        query_services = f'''
            SELECT ss.spot_id, sv.name, sv.category
            FROM spot_service ss
            JOIN services sv ON ss.service_id = sv.id
            WHERE ss.spot_id IN ({format_strings})
        '''
        cursor.execute(query_services, tuple(spot_ids))
        for row in cursor.fetchall():
            spot_id = row["spot_id"]
            service = row["name"]
            if spot_id not in services_map:
                services_map[spot_id] = []
            services_map[spot_id].append(service)

    # Construire la réponse, avec les champs prêts à afficher (catégorie prix,
    # badge, icônes des services...) calculés en Python par enrich_spot.
    result = []
    for spot in spots:
        result.append(enrich_spot({
            "id": spot["id"],
            "name": spot["name"],
            "description": spot["description"],
            "type": spot["type"],
            "latitude": spot["latitude"],
            "longitude": spot["longitude"],
            "rating": spot["rating"],
            "url": spot["url"],
            "verifie": spot["verifie"],
            "address": spot["address"],
            "services": services_map.get(spot["id"], [])
        }))

    cursor.close()
    MySQLUtils.disconnect(cnx)
    return result

@router.put("/update_plan/{plan_id}",summary="Update an existing trip plan with new data.")
def update_plan(plan_id: int, data: dict = Body(...)):
    plan_id = insert_or_update_plan(plan_id, data)
    return {"status": "updated", "plan_id": plan_id, "recap": data}
