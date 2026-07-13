from fastapi import APIRouter, Query, Body
from services.plan_service import insert_or_update_plan
from utils.db_utils import MySQLUtils
from utils.display_utils import enrich_hike
from utils.logger_util import LoggerUtil

router = APIRouter()
logger = LoggerUtil.get_logger(__name__)

@router.get("/hikes", summary="Returns the hikes for a given city with details.")
def get_hikes(
    city_id: int = Query(..., description="ID de la ville"),
    distance_km: float = Query(5, description="Rayon de recherche en km autour de la ville")
):
    """
    Retourne les randonnées pour une ville donnée avec tous les détails :
    - difficulte, duration, verifie, name, distance_km,
    - start_latitude, start_longitude, elevation_gain_m

    Vérifiées ou non, quel que soit le statut de connexion de l'utilisateur.
    """
    logger.info(f"Route /hikes appelée avec city_id={city_id}")
    cnx = MySQLUtils.connect()
    cursor = cnx.cursor(dictionary=True)
    
    # Récupérer les coordonnées de la ville
    cursor.execute(
        "SELECT latitude, longitude FROM cities WHERE id = %s", 
        (city_id,)
    )
    city = cursor.fetchone()
    
    if not city:
        cursor.close()
        MySQLUtils.disconnect(cnx)
        return []
    
    # Calculer la bounding box autour de la ville
    from utils.geo_utils import get_bounding_box
    min_lat, min_lon, max_lat, max_lon = get_bounding_box(
        city['latitude'], 
        city['longitude'], 
        distance_km
    )
    
    # Toutes les randonnées (vérifiées et non vérifiées)
    query = """
        SELECT
            id,
            name,
            difficulte,
            estimated_duration_h as duration,
            distance_km,
            start_latitude,
            start_longitude,
            elevation_gain_m,
            verifie,
            description,
            city_id
        FROM hikes
        WHERE start_latitude BETWEEN %s AND %s
        AND start_longitude BETWEEN %s AND %s
        ORDER BY name ASC
    """

    cursor.execute(query, (min_lat, max_lat, min_lon, max_lon))
    hikes = cursor.fetchall()

    cursor.close()
    MySQLUtils.disconnect(cnx)

    # Champs prêts à afficher (badge, catégories, libellés) calculés en Python :
    # le frontend n'a plus qu'à les insérer dans la page.
    return [enrich_hike(h, i, len(hikes)) for i, h in enumerate(hikes)]

@router.get("/hike/{hike_id}/trace", summary="Get GPS trace points for a hike from MongoDB.")
def get_hike_trace(hike_id: int):
    """Retourne les points lat/lon de la trace GPX depuis MongoDB."""
    from utils.mongo_utils import MongoUtils
    from bson import ObjectId

    cnx = MySQLUtils.connect()
    cursor = cnx.cursor(dictionary=True)
    cursor.execute("SELECT mongo_id FROM hikes WHERE id = %s", (hike_id,))
    hike = cursor.fetchone()
    cursor.close()
    MySQLUtils.disconnect(cnx)

    if not hike or not hike.get("mongo_id"):
        return {"points": []}

    try:
        MongoUtils.connect()
        doc = MongoUtils.get_collection("gpx_traces").find_one({"_id": ObjectId(hike["mongo_id"])})
        MongoUtils.disconnect()
        if not doc or not doc.get("points"):
            return {"points": []}
        return {"points": [{"lat": p["lat"], "lon": p["lon"]} for p in doc["points"]]}
    except Exception as e:
        logger.error(f"Erreur récupération trace hike {hike_id}: {e}")
        return {"points": []}


@router.put("/update_plan/{plan_id}", summary="Update an existing trip plan with new data.")
def update_plan(plan_id: int, data: dict = Body(...)):
    plan_id = insert_or_update_plan(plan_id, data)
    return {"status": "updated", "plan_id": plan_id, "recap": data}
