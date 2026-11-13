from datetime import date, timedelta

from fastapi import APIRouter, Query, Body, Depends, Request
from api.dependencies import require_plan_owner
from api.rate_limit import DAY_CHOICE_MESSAGE, DAY_SPOT_LIMIT, limiter
from services.pepite_service import start_preparation
from services.plan_service import insert_or_update_plan
from services.spot_selection_service import proposable_spots
from services.supervision_service import reworked_a_savoir
from utils.display_utils import SPOT_ON_HIKE_KM, enrich_spot
from utils.logger_util import LoggerUtil
from utils.db_utils import MySQLUtils
from utils.geo_utils import distance_to_trace_km

router = APIRouter()
logger = LoggerUtil.get_logger(__name__)

@router.get("/spots", summary="Returns the spots for a given city.")
def get_spots(
    city_id: int = Query(..., description="ID de la ville"),
    distance_km: float = Query(5, description="Rayon de la zone en km"),
    hike_id: int | None = Query(None, description="Rando du jour : spots triés selon leur distance à son tracé"),
    plan_id: int | None = Query(None, description="Séjour : avec day_number, donne la date de la nuit"),
    day_number: int = Query(1, description="Jour du séjour")
):
    """
    Retourne les spots (bivouac, camping, aire CC) pour une ville donnée,
    vérifiés ou non, quel que soit le statut de connexion de l'utilisateur.
    Avec la rando du jour, chaque spot porte sa distance au tracé : ceux à moins de
    500 m (SPOT_ON_HIKE_KM) sont « sur ta rando », même un peu au-delà du rayon de
    la ville, et la liste va du plus proche au plus loin de la rando.
    """
    logger.info(f"Route /spots appelée avec city_id={city_id}, distance_km={distance_km}")

    # Connexion DB
    from utils.geo_utils import get_bounding_box
    cnx = MySQLUtils.connect()
    cursor = cnx.cursor(dictionary=True)
    # try/finally : la connexion est fermée même en cas d'erreur. Sinon elle reste
    # ouverte avec une lecture en cours, et bloque toute modification de la table.
    try:
        night = _night_date(cursor, plan_id, day_number)
        return _spots_around_city(cnx, cursor, city_id, distance_km, get_bounding_box, _hike_trace(cursor, hike_id),
                                  night)
    finally:
        cursor.close()
        MySQLUtils.disconnect(cnx)


def _night_date(cursor, plan_id, day_number) -> date:
    """Date de la nuit à passer sur le spot : un lieu qui aura rouvert d'ici là peut être proposé."""
    if plan_id:
        cursor.execute("SELECT start_date FROM trip_plans WHERE id = %s", (plan_id,))
        plan = cursor.fetchone()
        if plan and plan["start_date"]:
            return plan["start_date"] + timedelta(days=day_number - 1)
    return date.today()


def _hike_trace(cursor, hike_id) -> list:
    """Points (latitude, longitude) du tracé de la rando du jour, [] sans rando ou sans tracé."""
    if not hike_id:
        return []
    from services.pepite_service import hike_trace
    cursor.execute("SELECT mongo_id FROM hikes WHERE id = %s", (hike_id,))
    hike = cursor.fetchone()
    return hike_trace(hike["mongo_id"]) if hike and hike.get("mongo_id") else []


def _spots_around_city(connection, cursor, city_id, distance_km, get_bounding_box, trace=(), night=None) -> list:
    """Spots autour d'une ville, prêts à afficher (voir get_spots)."""
    # Récupérer les coordonnées de la ville
    cursor.execute("SELECT latitude, longitude FROM cities WHERE id = %s", (city_id,))
    city = cursor.fetchone()
    if not city:
        return []

    city_box = get_bounding_box(city['latitude'], city['longitude'], distance_km)
    min_lat, min_lon, max_lat, max_lon = city_box
    if trace:
        # La rando peut sortir du rayon de la ville : on cherche aussi le long du tracé.
        south, west, _, _ = get_bounding_box(min(p[0] for p in trace), min(p[1] for p in trace), SPOT_ON_HIKE_KM)
        _, _, north, east = get_bounding_box(max(p[0] for p in trace), max(p[1] for p in trace), SPOT_ON_HIKE_KM)
        min_lat, min_lon, max_lat, max_lon = min(min_lat, south), min(min_lon, west), max(max_lat, north), max(max_lon, east)

    spots = proposable_spots(connection, cursor, (min_lat, min_lon, max_lat, max_lon), night or date.today())
    if trace:
        for spot in spots:
            spot["hike_distance_km"] = distance_to_trace_km(spot["latitude"], spot["longitude"], trace)
        # Hors du rayon de la ville, on ne garde que les spots sur le trajet de la rando.
        spots = [s for s in spots if s["hike_distance_km"] <= SPOT_ON_HIKE_KM
                 or (city_box[0] <= s["latitude"] <= city_box[2] and city_box[1] <= s["longitude"] <= city_box[3])]
        spots.sort(key=lambda s: s["hike_distance_km"])

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
            # On garde la catégorie : l'affichage fait un badge par catégorie.
            service = {"name": row["name"], "category": row["category"]}
            if spot_id not in services_map:
                services_map[spot_id] = []
            services_map[spot_id].append(service)

    a_savoir = reworked_a_savoir(cursor, spot_ids, night or date.today())

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
            "place_label": spot["place_label"],
            "city_label": spot["city_label"],
            "description_ia": spot["description_ia"],
            "prompt_version": spot["prompt_version"],
            "hike_distance_km": spot.get("hike_distance_km"),
            "a_savoir": a_savoir.get(spot["id"]),
            "services": services_map.get(spot["id"], [])
        }))

    return result

@router.put("/update_plan/{plan_id}", summary="Update an existing trip plan with new data.",
            dependencies=[Depends(require_plan_owner)])
# Le spot choisi lance la préparation des pépites de Vany (carte #21).
@limiter.limit(DAY_SPOT_LIMIT, error_message=DAY_CHOICE_MESSAGE)
def update_plan(request: Request, plan_id: int, data: dict = Body(...)):
    plan_id = insert_or_update_plan(plan_id, data)
    # Le spot est choisi : on prépare tout de suite, en tâche de fond, les idées
    # (pépites de Vany) du jour, pour qu'elles soient prêtes au récap.
    if data.get("spot_id"):
        start_preparation(plan_id, data.get("day_number", 1))
    return {"status": "updated", "plan_id": plan_id, "recap": data}
