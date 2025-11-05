from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional
from services.authentification import verify_access_token, get_roles_for_user
from fastapi import APIRouter, Body, HTTPException, Query, Request, Depends
from utils.logger_util import LoggerUtil
from utils.db_utils import MySQLUtils
from etl.etl_meteo import run_meteo_etl
from api.models.cities import CityList
from utils.meteo_utils import meteo_code_to_picto
from utils.geo_utils import get_bounding_box
from typing import List
from datetime import datetime, timedelta

router = APIRouter()
logger = LoggerUtil.get_logger("router")
security = HTTPBearer(auto_error=False)

def get_city_stats(cursor, latitude, longitude, user_role, distance_km=5):
    min_lat, min_lon, max_lat, max_lon = get_bounding_box(latitude, longitude, distance_km)
    # Randonnées vérifiées
    cursor.execute("""
        SELECT COUNT(*) as count FROM hikes WHERE verifie = 1 AND start_latitude BETWEEN %s AND %s AND start_longitude BETWEEN %s AND %s
    """, (min_lat, max_lat, min_lon, max_lon))
    hikes_verified = cursor.fetchone()['count']
    # Randonnées en attente
    cursor.execute("""
        SELECT COUNT(*) as count FROM hikes WHERE verifie = 0 AND start_latitude BETWEEN %s AND %s AND start_longitude BETWEEN %s AND %s
    """, (min_lat, max_lat, min_lon, max_lon))
    hikes_in_waiting = cursor.fetchone()['count']
    # Spots (POI) en attente
    cursor.execute("""
        SELECT COUNT(*) as count FROM spots WHERE verifie = 0 AND latitude BETWEEN %s AND %s AND longitude BETWEEN %s AND %s
    """, (min_lat, max_lat, min_lon, max_lon))
    spots_in_waiting = cursor.fetchone()['count']
    # Spots (POI) vérifiés
    cursor.execute("""
        SELECT COUNT(*) as count FROM spots WHERE verifie = 1 AND latitude BETWEEN %s AND %s AND longitude BETWEEN %s AND %s
    """, (min_lat, max_lat, min_lon, max_lon))
    spots_verified = cursor.fetchone()['count']
    # Services (POI) en attente
    cursor.execute("""
        SELECT COUNT(*) AS count FROM poi WHERE verifie = 0 AND latitude BETWEEN %s AND %s AND longitude BETWEEN %s AND %s
    """, (min_lat, max_lat, min_lon, max_lon))
    poi_in_waiting = cursor.fetchone()['count']
    # Services (POI) vérifiés
    cursor.execute("""
        SELECT COUNT(*) AS count FROM poi WHERE verifie = 1 AND latitude BETWEEN %s AND %s AND longitude BETWEEN %s AND %s
    """, (min_lat, max_lat, min_lon, max_lon))
    poi_verified = cursor.fetchone()['count']
    if user_role != "user":
        hikes=hikes_in_waiting+hikes_verified
        spots=spots_in_waiting+spots_verified
        poi=poi_in_waiting+poi_verified
    else:
        hikes=hikes_verified
        spots=spots_verified
        poi=poi_verified
    return {
        "hikes": hikes,
        "spots": spots,
        "poi": poi
    }

@router.get("/cities", response_model=List[CityList], summary="Returns the list of cities with statistics and updated weather forecasts.")
async def get_ville_list(
    request: Request,
    distance_km: float = Query(5, description="Rayon de recherche en km"),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
):
    # Extraire le rôle utilisateur via authentification.py
    user_role = "user"
    token = credentials.credentials if credentials else None
    logger.info(f"Header Authorization reçu: {token}")
    if token:
        try:
            payload = verify_access_token(token)
            user_id = payload.get('user_id')
            roles = get_roles_for_user(user_id)
            logger.info(f"Rôles trouvés pour l'utilisateur {user_id}: {roles}")
            user_role = next(iter(roles), "user")
        except Exception as e:
            logger.warning(f"Impossible de vérifier le token ou récupérer le rôle: {e}")
            user_role = "user"
    cnx = MySQLUtils.connect()
    cursor = cnx.cursor(dictionary=True)

    # Vérification si les données météo J+6 existent (7 jours de prévisions : J+0 à J+6)
    date_j6 = datetime.now().date() + timedelta(days=6)
    cursor.execute("SELECT COUNT(*) as count FROM weather WHERE date >= %s", (date_j6,))
    result = cursor.fetchone()
    meteo_j7_exists = result['count'] > 0

    # Si les données J+6 n'existent pas, lancer l'ETL météo pour toutes les villes
    if not meteo_j7_exists:
        logger.info("Lancement de l'ETL météo pour toutes les villes...")
        cursor.execute("SELECT id, name FROM cities")
        cities = cursor.fetchall()
        for city in cities:
            try:
                logger.info(f"Lancement ETL météo pour la ville : {city['name']}")
                run_meteo_etl(city['name'])
            except Exception as e:
                logger.error(f"Erreur ETL météo pour {city['name']}: {e}")

    cursor.execute("SELECT id, name, department, region, country, latitude, longitude FROM cities ORDER BY name ASC")
    cities = []
    for row in cursor.fetchall():
        row["stats"] = get_city_stats(cursor, row["latitude"], row["longitude"], user_role, distance_km)

        # Récupération des prévisions météo pour cette ville
        cursor.execute("SELECT * FROM weather WHERE city_id = %s AND DATE >= CURDATE() ORDER BY date ASC", (row['id'],))
        meteo_data = cursor.fetchall()
        forecasts = []
        for m in meteo_data:
            forecasts.append({
                "date": m["date"],
                "temp_max": m["temp_max_c"],
                "temp_min": m["temp_min_c"],
                "weather_code": m["weather_code"],
                "picto": meteo_code_to_picto(m["weather_code"]),
                "precipitation_sum": m.get("precipitation_mm", 0.0),
                "wind_speed_max": m.get("wind_max_kmh", 0.0)
            })
        row["meteo"] = forecasts

        cities.append(row)
    cursor.close()
    MySQLUtils.disconnect(cnx)
    return cities


@router.post("/create_plan", summary="Create a new trip plan with empty days.")
def create_plan(
    city_id: int = Body(...),
    duration_days: int = Body(...),
    user_token: str = Body(None),
    user_id: int = Body(None)
):
    """Créer un nouveau plan (trip_plans + jours vides pour l'étape 1)"""
    # On doit avoir soit user_id (connecté), soit user_token (invité)
    if user_id is None and (user_token is None or user_token.strip() == ""):
        raise HTTPException(status_code=400, detail="Un identifiant utilisateur ou un jeton invité est requis.")
    # Si user_id est None, on met 0 (pour invités)
    if user_id is None:
        user_id_to_insert = 0
    else:
        user_id_to_insert = user_id
    # Si user_token est None, on met None (pour connectés)
    user_token_to_insert = user_token if user_token else None
    try:
        cnx = MySQLUtils.connect()
        cursor = cnx.cursor()
        from datetime import date
        today = date.today()
        insert_plan = """
            INSERT INTO trip_plans (start_date, duration_days, city_id, user_token, user_id, created_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
        """
        cursor.execute(insert_plan, (today, duration_days, city_id, user_token_to_insert, user_id_to_insert))
        plan_id = cursor.lastrowid
        insert_day = """
            INSERT INTO trip_days (trip_plan_id, day_number, hike_id, spot_id)
            VALUES (%s, %s, NULL, NULL)
        """
        for day_num in range(1, duration_days + 1):
            cursor.execute(insert_day, (plan_id, day_num))
        cnx.commit()
        cursor.close()
        MySQLUtils.disconnect(cnx)
        return {"plan_id": plan_id, "message": "Plan créé avec succès."}
    except Exception as e:
        if 'cnx' in locals():
            cnx.rollback()
            MySQLUtils.disconnect(cnx)
        raise HTTPException(status_code=500, detail=f"Erreur lors de la création du plan : {str(e)}")


