from fastapi import APIRouter, Query, Body, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional
from services.plan_service import insert_or_update_plan
from services.authentification import verify_access_token, get_roles_for_user
from utils.logger_util import LoggerUtil
from utils.db_utils import MySQLUtils

router = APIRouter()
security = HTTPBearer(auto_error=False)
logger = LoggerUtil.get_logger(__name__)

@router.get("/spots", summary="Returns the spots for a given city.")
def get_spots(
    city_id: int = Query(..., description="ID de la ville"),
    distance_km: float = Query(5, description="Rayon de la zone en km"),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
):
    """
    Retourne les spots (bivouac, camping, aire CC) pour une ville donnée.

    Authentification optionnelle via JWT token :
    - Si token présent et valide : extraction du user_id et user_role depuis le token
    - Si user_role = "admin" ou "contributor" : retourne TOUS les spots (vérifiés + non vérifiés)
    - Si user_role = "user" OU aucun token : retourne uniquement les spots vérifiés (verifie = 1)
    """
    user_role = "user"  # Rôle par défaut pour utilisateurs non authentifiés
    user_id = None
    
    # Extraire le rôle depuis le JWT token si présent
    if credentials:
        logger.info("Token JWT reçu dans /spots")
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
    
    logger.info(f"Route /spots appelée avec city_id={city_id}, distance_km={distance_km}, user_role={user_role}")

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

    # Récupérer les spots dans la bounding box
    if user_role != "user":
            query = '''
                    SELECT s.id, s.name, s.description, s.type, s.latitude, s.longitude, s.rating, s.url, s.verifie
                    FROM spots s
                    WHERE s.latitude BETWEEN %s AND %s
                        AND s.longitude BETWEEN %s AND %s
                    ORDER BY s.name ASC
                '''
            cursor.execute(query, (min_lat, max_lat, min_lon, max_lon))
    else:
            query = '''
                        SELECT s.id, s.name, s.description, s.type, s.latitude, s.longitude, s.rating, s.url, s.verifie
                        FROM spots s
                        WHERE s.latitude BETWEEN %s AND %s
                            AND s.longitude BETWEEN %s AND %s
                            AND s.verifie = 1
                        ORDER BY s.name ASC
                '''
            cursor.execute(query, (min_lat, max_lat, min_lon, max_lon))
    spots = cursor.fetchall()

    # Récupérer les services associés à chaque spot
    '''
    spot_ids = [spot["id"] for spot in spots]
    services_map = {}
    if spot_ids:
        format_strings = ','.join(['%s'] * len(spot_ids))
        cursor.execute(f''''''
        cnx = MySQLUtils.connect()
        cursor = cnx.cursor(dictionary=True)
            JOIN services sv ON ss.service_id = sv.id
            WHERE ss.spot_id IN ({format_strings})
        '''''', tuple(spot_ids))
        for row in cursor.fetchall():
            spot_id = row["spot_id"]
            service = {"name": row["name"], "category": row["category"]}
            if spot_id not in services_map:
                services_map[spot_id] = []
            services_map[spot_id].append(service)
    '''
    # Construire la réponse
    result = []
    for spot in spots:
        result.append({
            "id": spot["id"],
            "name": spot["name"],
            "description": spot["description"],
            "type": spot["type"],
            "latitude": spot["latitude"],
            "longitude": spot["longitude"],
            "rating": spot["rating"],
            "url": spot["url"],
            "verifie": spot["verifie"],
            #"services": services_map.get(spot["id"], [])
        })

    cursor.close()
    MySQLUtils.disconnect(cnx)
    return result

@router.put("/update_plan/{plan_id}",summary="Update an existing trip plan with new data.")
def update_plan(plan_id: int, data: dict = Body(...)):
    plan_id = insert_or_update_plan(plan_id, data)
    return {"status": "updated", "plan_id": plan_id, "recap": data}
