from fastapi import APIRouter, Body, HTTPException, Query, Request
from utils.logger_util import LoggerUtil
from utils.db_utils import MySQLUtils
from etl.etl_meteo import run_meteo_etl
from api.models.cities import CityList
from utils.meteo_utils import meteo_code_to_picto
from utils.service_utils import POI_FRONTEND_CATEGORY_MAP
from services.plan_service import set_day_city
from typing import List
from datetime import datetime, timedelta, date
import time
import threading

router = APIRouter()
logger = LoggerUtil.get_logger("router")

# Verrou pour empêcher plusieurs rafraîchissements météo globaux en parallèle
meteo_refresh_lock = threading.Lock()
meteo_refresh_in_progress = False


def refresh_all_cities_meteo_background():
    """Rafraîchit la météo de toutes les villes en arrière-plan (thread séparé, non bloquant)."""
    global meteo_refresh_in_progress
    try:
        cnx = MySQLUtils.connect()
        cursor = cnx.cursor(dictionary=True)
        cursor.execute("SELECT id, name, latitude, longitude FROM cities")
        cities = cursor.fetchall()
        cursor.close()
        MySQLUtils.disconnect(cnx)

        logger.info(f"[METEO-BG] Début du rafraîchissement météo en arrière-plan pour {len(cities)} villes")
        for idx, city in enumerate(cities):
            try:
                logger.info(f"[METEO-BG] Lancement ETL météo pour la ville : {city['name']} ({idx + 1}/{len(cities)})")
                run_meteo_etl(city['name'], city['latitude'], city['longitude'])
                if idx < len(cities) - 1:
                    time.sleep(2)
            except Exception as e:
                logger.error(f"[METEO-BG] Erreur ETL météo pour {city['name']}: {e}")
        logger.info("[METEO-BG] Rafraîchissement météo en arrière-plan terminé")
    finally:
        with meteo_refresh_lock:
            meteo_refresh_in_progress = False

def get_all_city_stats(cursor, cities, distance_km=5):
    """
    Calcule les stats (randonnées, spots, POI) pour TOUTES les villes en une poignée
    de requêtes agrégées (une par table), au lieu d'une boucle de 6 requêtes par ville.
    Scalable même si la base grossit avec de nouveaux départements : le nombre de
    requêtes ne dépend plus du nombre de villes.
    Retourne un dict {city_id: {"hikes", "spots", "poi"}}.
    """
    city_ids = [c["id"] for c in cities]
    stats = {cid: {"hikes": 0, "spots": 0, "poi": 0} for cid in city_ids}
    if not city_ids:
        return stats

    # Delta de latitude constant (même distance_km pour toutes les villes) ; le delta de
    # longitude varie par ville car il dépend du cosinus de sa latitude (calculé en SQL).
    lat_delta = distance_km / 111.32
    def bbox_on(alias, lat_col, lon_col):
        return f"""
            ON {alias}.{lat_col} BETWEEN c.latitude - %s AND c.latitude + %s
           AND {alias}.{lon_col} BETWEEN c.longitude - (%s / COS(RADIANS(c.latitude))) AND c.longitude + (%s / COS(RADIANS(c.latitude)))
        """
    bbox_params = (lat_delta, lat_delta, lat_delta, lat_delta)

    cursor.execute(f"""
        SELECT c.id AS city_id, COUNT(*) AS cnt
        FROM cities c
        JOIN hikes h {bbox_on("h", "start_latitude", "start_longitude")}
        GROUP BY c.id
    """, bbox_params)
    for row in cursor.fetchall():
        if row["city_id"] in stats:
            stats[row["city_id"]]["hikes"] = row["cnt"]

    cursor.execute(f"""
        SELECT c.id AS city_id, COUNT(*) AS cnt
        FROM cities c
        JOIN spots sp {bbox_on("sp", "latitude", "longitude")}
        GROUP BY c.id
    """, bbox_params)
    for row in cursor.fetchall():
        if row["city_id"] in stats:
            stats[row["city_id"]]["spots"] = row["cnt"]

    # Services (POI) : uniquement les catégories affichées en step4 (même règle que POI_FRONTEND_CATEGORY_MAP)
    valid_categories = list(POI_FRONTEND_CATEGORY_MAP.keys())
    placeholders = ",".join(["%s"] * len(valid_categories))
    cursor.execute(f"""
        SELECT c.id AS city_id, COUNT(DISTINCT p.id) AS cnt
        FROM cities c
        JOIN poi p {bbox_on("p", "latitude", "longitude")}
        JOIN poi_service ps ON p.id = ps.poi_id
        JOIN services s ON ps.service_id = s.id
        WHERE s.category IN ({placeholders})
        GROUP BY c.id
    """, bbox_params + tuple(valid_categories))
    for row in cursor.fetchall():
        if row["city_id"] in stats:
            stats[row["city_id"]]["poi"] = row["cnt"]

    return stats

@router.get("/cities/bounds", summary="Returns the bounding box covering all available cities.")
def get_cities_bounds():
    """
    Emprise géographique de toutes les villes en base (min/max lat/lon). Utilisée
    par le front pour brider le panoramique/zoom des cartes à la zone réellement
    couverte (pas de sens d'aller voir les États-Unis, aucune ville n'y est
    référencée) — calculée dynamiquement, pas codée en dur, pour suivre l'ajout
    de nouveaux départements sans changement de code.
    """
    cnx = MySQLUtils.connect()
    cursor = cnx.cursor(dictionary=True)
    cursor.execute("""
        SELECT MIN(latitude) AS min_lat, MAX(latitude) AS max_lat,
               MIN(longitude) AS min_lon, MAX(longitude) AS max_lon
        FROM cities
    """)
    bounds = cursor.fetchone()
    cursor.close()
    MySQLUtils.disconnect(cnx)
    return bounds

@router.get("/cities", response_model=List[CityList], summary="Returns the list of cities with statistics and updated weather forecasts.")
async def get_ville_list(
    request: Request,
    distance_km: float = Query(5, description="Rayon de recherche en km")
):
    cnx = MySQLUtils.connect()
    cursor = cnx.cursor(dictionary=True)

    # Vérification si les données météo J+6 existent (7 jours de prévisions : J+0 à J+6)
    date_j6 = datetime.now().date() + timedelta(days=6)
    cursor.execute("SELECT COUNT(*) as count FROM weather WHERE date >= %s", (date_j6,))
    result = cursor.fetchone()
    meteo_j7_exists = result['count'] > 0

    # Si les données J+6 n'existent pas, lancer l'ETL météo pour toutes les villes en arrière-plan
    # (non bloquant : la requête répond avec les données déjà en base pendant que le rafraîchissement se fait)
    if not meteo_j7_exists:
        global meteo_refresh_in_progress
        with meteo_refresh_lock:
            already_running = meteo_refresh_in_progress
            if not already_running:
                meteo_refresh_in_progress = True
        if not already_running:
            logger.info("Lancement de l'ETL météo en arrière-plan pour toutes les villes...")
            threading.Thread(target=refresh_all_cities_meteo_background, daemon=True).start()
        else:
            logger.info("Rafraîchissement météo déjà en cours en arrière-plan.")

    cursor.execute("SELECT id, name, department, region, country, latitude, longitude FROM cities ORDER BY name ASC")
    cities = cursor.fetchall()

    # Stats de toutes les villes en une poignée de requêtes agrégées (voir get_all_city_stats)
    # au lieu d'une boucle de 6 requêtes par ville.
    all_stats = get_all_city_stats(cursor, cities, distance_km)

    # Météo de toutes les villes en une seule requête, regroupée ensuite par ville en Python.
    city_ids = [c["id"] for c in cities]
    meteo_by_city = {cid: [] for cid in city_ids}
    if city_ids:
        placeholders = ",".join(["%s"] * len(city_ids))
        cursor.execute(
            f"SELECT * FROM weather WHERE city_id IN ({placeholders}) AND DATE >= CURDATE() ORDER BY city_id, date ASC",
            tuple(city_ids)
        )
        for m in cursor.fetchall():
            meteo_by_city[m["city_id"]].append({
                "date": m["date"],
                "temp_max": m["temp_max_c"],
                "temp_min": m["temp_min_c"],
                "weather_code": m["weather_code"],
                "picto": meteo_code_to_picto(m["weather_code"]),
                "precipitation_sum": m.get("precipitation_mm", 0.0),
                "wind_speed_max": m.get("wind_max_kmh", 0.0)
            })

    for row in cities:
        row["stats"] = all_stats[row["id"]]
        row["meteo"] = meteo_by_city[row["id"]]

    cursor.close()
    MySQLUtils.disconnect(cnx)
    return cities


@router.post("/create_plan", summary="Create a new trip plan with empty days.")
def create_plan(
    city_id: int = Body(...),
    duration_days: int = Body(...),
    user_token: str = Body(None),
    user_id: int = Body(None),
    start_date: date = Body(None)
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
        plan_start_date = start_date or date.today()
        insert_plan = """
            INSERT INTO trip_plans (start_date, duration_days, city_id, user_token, user_id, created_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
        """
        cursor.execute(insert_plan, (plan_start_date, duration_days, city_id, user_token_to_insert, user_id_to_insert))
        plan_id = cursor.lastrowid
        insert_day = """
            INSERT INTO trip_days (trip_plan_id, day_number, hike_id, spot_id, city_id)
            VALUES (%s, %s, NULL, NULL, %s)
        """
        for day_num in range(1, duration_days + 1):
            cursor.execute(insert_day, (plan_id, day_num, city_id))
        cnx.commit()
        cursor.close()
        MySQLUtils.disconnect(cnx)
        return {"plan_id": plan_id, "message": "Plan créé avec succès."}
    except Exception as e:
        if 'cnx' in locals():
            cnx.rollback()
            MySQLUtils.disconnect(cnx)
        raise HTTPException(status_code=500, detail=f"Erreur lors de la création du plan : {str(e)}")


@router.put("/update_day_city/{plan_id}", summary="Set (or change) the city for a given day of the trip.")
def update_day_city(plan_id: int, data: dict = Body(...)):
    """Fixe la ville d'un jour du séjour, appelé à chaque transition de jour depuis /results."""
    day_number = data.get("day_number")
    city_id = data.get("city_id")
    if day_number is None or city_id is None:
        raise HTTPException(status_code=400, detail="day_number et city_id sont requis.")
    set_day_city(plan_id, day_number, city_id)
    return {"status": "updated", "plan_id": plan_id, "day_number": day_number, "city_id": city_id}


@router.get("/refresh-meteo/{city_id}", summary="Refresh weather data for a specific city")
async def refresh_city_meteo(city_id: int):
    """Lancer l'ETL météo pour une ville spécifique (en cas de données manquantes)"""
    try:
        cnx = MySQLUtils.connect()
        cursor = cnx.cursor(dictionary=True)
        
        # Récupérer le nom et les coordonnées de la ville
        cursor.execute("SELECT name, latitude, longitude FROM cities WHERE id = %s", (city_id,))
        result = cursor.fetchone()

        if not result:
            cursor.close()
            MySQLUtils.disconnect(cnx)
            raise HTTPException(status_code=404, detail="Ville non trouvée")

        city_name = result['name']
        logger.info(f"[REFRESH] Lancement ETL météo pour la ville : {city_name}")

        # Lancer l'ETL météo avec les coordonnées DB (évite l'appel Nominatim)
        etl_result = run_meteo_etl(city_name, result['latitude'], result['longitude'])
        
        # Récupérer les prévisions météo fraîchement créées
        cursor.execute("SELECT * FROM weather WHERE city_id = %s AND DATE >= CURDATE() ORDER BY date ASC", (city_id,))
        meteo_data = cursor.fetchall()
        
        forecasts = []
        for m in meteo_data:
            forecasts.append({
                "date": str(m["date"]),
                "temp_max": m["temp_max_c"],
                "temp_min": m["temp_min_c"],
                "weather_code": m["weather_code"],
                "picto": meteo_code_to_picto(m["weather_code"]),
                "precipitation_sum": m.get("precipitation_mm", 0.0),
                "wind_speed_max": m.get("wind_max_kmh", 0.0)
            })
        
        cursor.close()
        MySQLUtils.disconnect(cnx)
        
        return {
            "city_id": city_id,
            "city_name": city_name,
            "meteo": forecasts,
            "etl_result": etl_result,
            "message": f"Données météo actualisées pour {city_name}"
        }
    except HTTPException:
        raise
    except Exception as e:
        if 'cnx' in locals():
            MySQLUtils.disconnect(cnx)
        logger.error(f"Erreur lors du refresh météo pour city_id {city_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur lors de l'actualisation météo : {str(e)}")


