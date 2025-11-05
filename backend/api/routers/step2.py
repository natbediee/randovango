from fastapi import APIRouter, Query, Body, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional
from services.plan_service import insert_or_update_plan
from utils.db_utils import MySQLUtils
from services.authentification import verify_access_token, get_roles_for_user
from utils.logger_util import LoggerUtil

router = APIRouter()
security = HTTPBearer(auto_error=False)
logger = LoggerUtil.get_logger(__name__)

@router.get("/hikes", summary="Returns the hikes for a given city with details.")
def get_hikes(
    city_id: int = Query(..., description="ID de la ville"),
    distance_km: float = Query(5, description="Rayon de recherche en km autour de la ville"),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
):
    """
    Retourne les randonnées pour une ville donnée avec tous les détails :
    - difficulte, duration, verifie, name, distance_km, 
    - start_latitude, start_longitude, elevation_gain_m
    
    Authentification optionnelle via JWT token :
    - Si token présent et valide : extraction du user_id et user_role depuis le token
    - Si user_role = "admin" ou "contributor" : retourne TOUTES les randonnées (vérifiées + non vérifiées)
    - Si user_role = "user" OU aucun token : retourne uniquement les randonnées vérifiées (verifie = 1)
    """
    user_role = "user"  # Rôle par défaut pour utilisateurs non authentifiés
    user_id = None
    
    # Extraire le rôle depuis le JWT token si présent
    if credentials:
        logger.info("Token JWT reçu dans /hikes")
        token = credentials.credentials
        try:
            payload = verify_access_token(token)
            user_id = payload.get('user_id')
            logger.info(f"User ID extrait du token : {user_id}")
            
            if user_id:
                roles = get_roles_for_user(user_id)
                logger.info(f"Rôles pour user_id {user_id} : {roles}")
                # Extraire le premier rôle du set (get_roles_for_user retourne un set)
                user_role = next(iter(roles), "user")
                logger.info(f"Rôle appliqué : {user_role}")
        except Exception as e:
            logger.warning(f"Erreur lors de la vérification du token : {str(e)}")
            user_role = "user"
    else:
        logger.info("Aucun token JWT fourni, rôle par défaut : user")
    
    logger.info(f"Route /hikes appelée avec city_id={city_id}, user_role={user_role}")
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
    
    # Construire la requête en fonction du rôle
    if user_role != "user":
        # Admin/Contributor : toutes les randonnées
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
    else:
        # User : uniquement les randonnées vérifiées
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
            AND verifie = 1
            ORDER BY name ASC
        """
    
    cursor.execute(query, (min_lat, max_lat, min_lon, max_lon))
    hikes = cursor.fetchall()
    
    cursor.close()
    MySQLUtils.disconnect(cnx)
    
    return hikes

@router.put("/update_plan/{plan_id}", summary="Update an existing trip plan with new data.")
def update_plan(plan_id: int, data: dict = Body(...)):
    plan_id = insert_or_update_plan(plan_id, data)
    return {"status": "updated", "plan_id": plan_id, "recap": data}
