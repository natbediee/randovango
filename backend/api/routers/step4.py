from fastapi import APIRouter, Query, Body
from services.plan_service import insert_or_update_plan
from utils.db_utils import MySQLUtils
from utils.display_utils import enrich_poi, poi_subtitle
from utils.service_utils import POI_FRONTEND_CATEGORY_MAP

router = APIRouter()

MAX_POI_PER_CATEGORY = 10


def _build_subtitles(categorized_poi: dict) -> dict:
    """Phrases "X services disponibles pour cette journée" par catégorie,
    prêtes à afficher (le frontend n'a plus qu'à piocher selon l'onglet actif).
    La clé "tout" totalise l'ensemble des catégories."""
    counts = {cat: len(pois) for cat, pois in categorized_poi.items()}
    counts["tout"] = sum(counts.values())
    return {cat: poi_subtitle(cat, count) for cat, count in counts.items()}

@router.get("/poi", summary="Returns the POI (points of interest/services) categorized by service type.")
def get_poi(
    city_id: int = Query(..., description="ID de la ville"),
    distance_km: float = Query(5, description="Rayon de recherche en km autour de la ville"),
    spot_lat: float = Query(None, description="Latitude du spot choisi, utilisée comme point de référence"),
    spot_lon: float = Query(None, description="Longitude du spot choisi, utilisée comme point de référence")
):
    """
    Retourne les POI (Points d'Intérêt / Services) pour une ville donnée,
    catégorisés par type de service (eau, vidange, gasoil, supermarche,
    commerce, restauration, toilettes, hygiene, culture, urgence).

    Tous les POI sont retournés (vérifiés + non vérifiés), quel que soit
    le statut de connexion de l'utilisateur.

    Les résultats de chaque catégorie sont limités aux MAX_POI_PER_CATEGORY
    POI les plus proches du spot choisi (ou du centre-ville à défaut), afin
    d'éviter une liste trop longue dans les grandes villes.
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
        empty = {
            "eau": [], "vidange": [], "gasoil": [], "supermarche": [], "commerce": [],
            "restauration": [],
            "toilettes": [],
            "hygiene": [],
            "culture": [],
            "urgence": []
        }
        empty["subtitles"] = _build_subtitles(empty)
        return empty
    
    # Calculer la bounding box autour de la ville
    from utils.geo_utils import get_bounding_box, haversine_distance_km
    min_lat, min_lon, max_lat, max_lon = get_bounding_box(
        city['latitude'],
        city['longitude'],
        distance_km
    )

    # Point de référence pour trier par proximité : le spot choisi si fourni, sinon le centre-ville
    ref_lat = spot_lat if spot_lat is not None else city['latitude']
    ref_lon = spot_lon if spot_lon is not None else city['longitude']
    
    # Tous les POI (vérifiés et non vérifiés)
    query = """
        SELECT
            p.id,
            p.name,
            p.description,
            p.latitude,
            p.longitude,
            p.verifie,
            p.image_url,
            p.url,
            p.address,
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

    cursor.execute(query, (min_lat, max_lat, min_lon, max_lon))
    poi_list = cursor.fetchall()
    
    cursor.close()
    MySQLUtils.disconnect(cnx)
    
    category_mapping = POI_FRONTEND_CATEGORY_MAP

    # Grouper les POI par catégorie
    categorized_poi = {
        "eau": [], "vidange": [], "gasoil": [], "supermarche": [], "commerce": [],
        "restauration": [],
        "toilettes": [],
        "hygiene": [],
        "culture": [],
        "urgence": []
    }
    seen_ids = {cat: set() for cat in categorized_poi}

    for poi in poi_list:
        service_cat = poi.get('service_category', '').lower()
        frontend_category = category_mapping.get(service_cat)
        if not frontend_category:
            continue

        poi_id = poi['id']
        if poi_id in seen_ids[frontend_category]:
            continue
        seen_ids[frontend_category].add(poi_id)

        distance_km = haversine_distance_km(ref_lat, ref_lon, poi['latitude'], poi['longitude'])

        categorized_poi[frontend_category].append(enrich_poi({
            "id": poi_id,
            "name": poi['name'],
            "description": poi['description'],
            "latitude": poi['latitude'],
            "longitude": poi['longitude'],
            "verifie": poi['verifie'],
            "image_url": poi['image_url'],
            "url": poi['url'],
            "address": poi['address'],
            "service_type": poi['service_name'],
            "distance_km": round(distance_km, 2)
        }))

    # Ne garder que les POI les plus proches du point de référence, par catégorie
    for category, pois in categorized_poi.items():
        pois.sort(key=lambda p: p['distance_km'])
        categorized_poi[category] = pois[:MAX_POI_PER_CATEGORY]

    # Phrases de sous-titre par catégorie, calculées APRÈS la troncature à
    # MAX_POI_PER_CATEGORY pour correspondre au nombre réellement affiché.
    categorized_poi["subtitles"] = _build_subtitles(categorized_poi)

    return categorized_poi

@router.put("/update_plan/{plan_id}",summary="Update an existing trip plan with new data.")
def update_plan(plan_id: int, data: dict = Body(...)):
    plan_id = insert_or_update_plan(plan_id, data)
    return {"status": "updated", "plan_id": plan_id, "recap": data}
