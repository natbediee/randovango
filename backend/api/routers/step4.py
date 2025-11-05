from fastapi import APIRouter, Query, Body
from services.plan_service import insert_or_update_plan
from utils.db_utils import MySQLUtils

router = APIRouter()

@router.get("/poi", summary="Returns the POI (points of interest/services) categorized by service type.")
def get_poi(
    city_id: int = Query(..., description="ID de la ville"),
    user_role: str = Query("user", description="Rôle de l'utilisateur (user, contributor, admin)"),
    distance_km: float = Query(5, description="Rayon de recherche en km autour de la ville")
):
    """
    Retourne les POI (Points d'Intérêt / Services) pour une ville donnée, 
    catégorisés par type de service (logistique, hygiene, culture, urgence).
    
    Si user_role != "user", retourne tous les POI (vérifiés + non vérifiés).
    Sinon, retourne uniquement les POI vérifiés.
    """
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
        return {
            "logistique": [],
            "hygiene": [],
            "culture": [],
            "urgence": []
        }
    
    # Calculer la bounding box autour de la ville
    from utils.geo_utils import get_bounding_box
    min_lat, min_lon, max_lat, max_lon = get_bounding_box(
        city['latitude'], 
        city['longitude'], 
        distance_km
    )
    
    # Construire la requête avec jointure pour récupérer les services
    if user_role != "user":
        # Admin/Contributor : tous les POI
        query = """
            SELECT 
                p.id,
                p.name,
                p.description,
                p.latitude,
                p.longitude,
                p.verifie,
                p.image_url,
                --
                s.category as service_category,
                s.name as service_name
            FROM poi p
            JOIN poi_service ps ON p.id = ps.poi_id
            JOIN services s ON ps.service_id = s.id
            WHERE p.latitude BETWEEN %s AND %s 
            AND p.longitude BETWEEN %s AND %s
            ORDER BY s.category, p.name ASC
        """
    else:
        # User : uniquement les POI vérifiés
        query = """
            SELECT 
                p.id,
                p.name,
                p.description,
                p.latitude,
                p.longitude,
                p.verifie,
                p.image_url,
                --
                s.category as service_category,
                s.name as service_name
            FROM poi p
            JOIN poi_service ps ON p.id = ps.poi_id
            JOIN services s ON ps.service_id = s.id
            WHERE p.latitude BETWEEN %s AND %s 
            AND p.longitude BETWEEN %s AND %s
            AND p.verifie = 1
            ORDER BY s.category, p.name ASC
        """
    
    cursor.execute(query, (min_lat, max_lat, min_lon, max_lon))
    poi_list = cursor.fetchall()
    
    cursor.close()
    MySQLUtils.disconnect(cnx)
    
    # Définir le mapping des catégories vers les groupes du frontend
    category_mapping = {
        "supermarket": "logistique",
        "fuel": "logistique",
        "drinking_water": "logistique",
        "water": "logistique",
        "toilets": "hygiene",
        "shower": "hygiene",
        "tourism": "culture",
        "attraction": "culture",
        "museum": "culture",
        "pharmacy": "urgence",
        "hospital": "urgence",
        "doctors": "urgence"
    }
    
    # Grouper les POI par catégorie
    categorized_poi = {
        "logistique": [],
        "hygiene": [],
        "culture": [],
        "urgence": []
    }
    
    for poi in poi_list:
        service_cat = poi.get('service_category', '').lower()
        # Déterminer la catégorie frontend
        frontend_category = category_mapping.get(service_cat, "logistique")
        
        poi_data = {
            "id": poi['id'],
            "name": poi['name'],
            "description": poi['description'],
            "latitude": poi['latitude'],
            "longitude": poi['longitude'],
            "verifie": poi['verifie'],
            "image_url": poi['image_url'],
            # "website": poi['website'],
            "service_type": poi['service_name']
        }
        
        categorized_poi[frontend_category].append(poi_data)
    
    return categorized_poi

@router.put("/update_plan/{plan_id}",summary="Update an existing trip plan with new data.")
def update_plan(plan_id: int, data: dict = Body(...)):
    plan_id = insert_or_update_plan(plan_id, data)
    return {"status": "updated", "plan_id": plan_id, "recap": data}
