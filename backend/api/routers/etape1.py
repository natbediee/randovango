
from fastapi import APIRouter, Body, HTTPException, Query
from utils.mysql_utils import MySQLUtils
from etl.etl_meteo import run_meteo_etl
from api.models.villes import VilleList, MeteoResponse
from utils.meteo_utils import meteo_code_to_picto
from utils.geo_utils import get_bounding_box
from typing import List
from datetime import datetime, timedelta

router = APIRouter()

def get_city_stats(cursor, latitude, longitude, user_role, distance_km=5):
    min_lat, min_lon, max_lat, max_lon = get_bounding_box(latitude, longitude, distance_km)
    # Randonnées vérifiées
    print("""
        SELECT COUNT(*) as count FROM hikes WHERE verifie = 1 AND start_latitude BETWEEN %s AND %s AND start_longitude BETWEEN %s AND %s
    """, (min_lat, max_lat, min_lon, max_lon))
    cursor.execute("""
        SELECT COUNT(*) as count FROM hikes WHERE verifie = 1 AND start_latitude BETWEEN %s AND %s AND start_longitude BETWEEN %s AND %s
    """, (min_lat, max_lat, min_lon, max_lon))
    randonnees_verifiees = cursor.fetchone()['count']
    # Randonnées en attente
    cursor.execute("""
        SELECT COUNT(*) as count FROM hikes WHERE verifie = 0 AND start_latitude BETWEEN %s AND %s AND start_longitude BETWEEN %s AND %s
    """, (min_lat, max_lat, min_lon, max_lon))
    randonnees_en_attente = cursor.fetchone()['count']
    # Spots (POI) en attente
    cursor.execute("""
        SELECT COUNT(*) as count FROM spots WHERE verifie = 0 AND latitude BETWEEN %s AND %s AND longitude BETWEEN %s AND %s
    """, (min_lat, max_lat, min_lon, max_lon))
    spots_en_attente = cursor.fetchone()['count']
    # Spots (POI) vérifiés
    cursor.execute("""
        SELECT COUNT(*) as count FROM spots WHERE verifie = 1 AND latitude BETWEEN %s AND %s AND longitude BETWEEN %s AND %s
    """, (min_lat, max_lat, min_lon, max_lon))
    spots_verifies = cursor.fetchone()['count']
    # Services (POI) en attente
    cursor.execute("""
        SELECT COUNT(*) AS count FROM poi WHERE verifie = 0 AND latitude BETWEEN %s AND %s AND longitude BETWEEN %s AND %s
    """, (min_lat, max_lat, min_lon, max_lon))
    poi_en_attente = cursor.fetchone()['count']
    # Services (POI) vérifiés
    cursor.execute("""
        SELECT COUNT(*) AS count FROM poi WHERE verifie = 1 AND latitude BETWEEN %s AND %s AND longitude BETWEEN %s AND %s
    """, (min_lat, max_lat, min_lon, max_lon))
    poi_verifies = cursor.fetchone()['count']
    if user_role != "user":
        randonnees=randonnees_en_attente+randonnees_verifiees
        spots=spots_en_attente+spots_verifies
        poi=poi_en_attente+poi_verifies
    else:
        randonnees=randonnees_verifiees
        spots=spots_verifies
        poi=poi_verifies
    return {
        "randonnees": randonnees,
        "spots": spots,
        "poi": poi
    }

@router.get("/villes", response_model=List[VilleList])
def get_ville_list(user_role: str = "user", distance_km: float = Query(5, description="Rayon de recherche en km")):
    cnx = MySQLUtils.connect()
    cursor = cnx.cursor(dictionary=True)
    
    # Vérification si les données météo J+6 existent (7 jours de prévisions : J+0 à J+6)
    date_j6 = datetime.now().date() + timedelta(days=6)
    cursor.execute("SELECT COUNT(*) as count FROM weather WHERE date >= %s", (date_j6,))
    result = cursor.fetchone()
    meteo_j7_exists = result['count'] > 0
    
    # Si les données J+6 n'existent pas, lancer l'ETL météo pour toutes les villes
    if not meteo_j7_exists:
        cursor.execute("SELECT id, name FROM cities")
        cities = cursor.fetchall()
        for city in cities:
            try:
                run_meteo_etl(city['name'])
            except Exception as e:
                print(f"Erreur ETL météo pour {city['name']}: {e}")
    
    cursor.execute("SELECT id, name, department, region, country, latitude, longitude FROM cities ORDER BY name ASC")
    villes = []
    for row in cursor.fetchall():
        row["stats"] = get_city_stats(cursor, row["latitude"], row["longitude"], user_role, distance_km)
        
        # Récupération des prévisions météo pour cette ville
        cursor.execute("SELECT * FROM weather WHERE city_id = %s ORDER BY date ASC", (row['id'],))
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
        
        villes.append(row)
    cursor.close()
    MySQLUtils.disconnect(cnx)
    return villes


@router.get("/ville/{ville_id}/meteo", response_model=MeteoResponse)
def get_meteo(ville_id: int):
    cnx = MySQLUtils.connect()
    cursor = cnx.cursor(dictionary=True)
    cursor.execute("SELECT name FROM cities WHERE id = %s", (ville_id,))
    row = cursor.fetchone()
    if not row:
        cursor.close()
        MySQLUtils.disconnect(cnx)
        raise HTTPException(status_code=404, detail="Ville inconnue")
    city_name = row['name']
    cursor.execute("SELECT * FROM weather WHERE city_id = %s ORDER BY date ASC", (ville_id,))
    meteo = cursor.fetchall()
    # Conversion vers le modèle MeteoForecast (picto à calculer selon weather_code)
    forecasts = []
    for m in meteo:
        forecasts.append({
            "date": m["date"],
            "temp_max": m["temp_max_c"],
            "temp_min": m["temp_min_c"],
            "weather_code": m["weather_code"],
            "picto": meteo_code_to_picto(m["weather_code"]),
            "precipitation_sum": m.get("precipitation_mm", 0.0),
            "wind_speed_max": m.get("wind_max_kmh", 0.0)
        })
    cursor.close()
    MySQLUtils.disconnect(cnx)
    return {"ville": city_name, "forecasts": forecasts, "updated_at": None}

# A DEVELOPPER
@router.post("/create_plan")
def create_plan(data: dict = Body(...)):
    #plan_id = insert_or_update_plan(None, data)
    pass  # À implémenter

