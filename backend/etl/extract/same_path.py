"""
Cherche en base une rando qui suit déjà le même chemin qu'un tracé qu'on vient de lire (issue #271).

Avant cette issue, seul le nom du fichier était comparé : le même tracé, renommé, entrait une seconde fois (Guidel le
19 novembre 2026, le Gouet Nord à Ploufragan le 23 novembre). Maintenant, le tracé lu est comparé aux tracés des randos
qui partent dans sa zone (trace_overlap). S'il recouvre l'une d'elles à 85 % ou plus, le fichier est refusé avec le
nom de cette rando et l'écart entre les deux départs : l'admin peut alors décider de le charger quand même, par exemple
quand un autre départ (un autre parking) a son intérêt pour le voyageur.
Un tracé identique (recouvert à 99 % ou plus, et parti du même endroit) est la même rando : il n'y a rien à décider,
et le refus est définitif, même pour l'admin (choix de l'utilisatrice du 28 novembre 2026).
"""
import math

from bson import ObjectId

from etl.transform.trace_overlap import overlap_share, DUPLICATE_SHARE
from utils.db_utils import MySQLUtils
from utils.geo_utils import haversine_distance_km
from utils.mongo_utils import MongoUtils

# La marge autour du tracé où l'on cherche les départs des randos à comparer. Le départ d'une rando qui recouvre le
# nouveau tracé est presque toujours sur ce tracé ; 5 km laissent de la place à une boucle commencée sur la petite
# partie qui n'est pas commune.
SEARCH_MARGIN_KM = 5.0
# En dessous de cet écart, les deux départs sont au même endroit (le GPS varie de quelques mètres).
SAME_START_M = 50
# À partir de ce recouvrement, et avec le même départ, les deux tracés sont identiques. 99 % et non 100 % : deux
# enregistrements du même chemin ne tombent pas toujours pile sur 100 %.
IDENTICAL_SHARE = 0.99


def search_box(points) -> tuple:
    """
    Le rectangle (lat min, lon min, lat max, lon max) qui contient tout le tracé, élargi de 5 km de chaque côté.
    Un degré de latitude fait 111,32 km ; un degré de longitude est plus court loin de l'équateur.
    """
    lats = [p["lat"] for p in points]
    lons = [p["lon"] for p in points]
    margin_lat = SEARCH_MARGIN_KM / 111.32
    margin_lon = SEARCH_MARGIN_KM / (111.32 * math.cos(math.radians(sum(lats) / len(lats))))
    return min(lats) - margin_lat, min(lons) - margin_lon, max(lats) + margin_lat, max(lons) + margin_lon


def candidate_hikes(points) -> list:
    """Les randos en base dont le départ tombe dans la zone du tracé, avec leur ville et l'id de leur tracé MongoDB."""
    min_lat, min_lon, max_lat, max_lon = search_box(points)
    with MySQLUtils.open_cursor(dictionary=True) as (conn, cursor):
        cursor.execute(
            "SELECT h.id, h.name, h.mongo_id, h.start_latitude, h.start_longitude, c.name AS city"
            " FROM hikes h LEFT JOIN cities c ON c.id = h.city_id"
            " WHERE h.mongo_id IS NOT NULL"
            " AND h.start_latitude BETWEEN %s AND %s AND h.start_longitude BETWEEN %s AND %s",
            (min_lat, max_lat, min_lon, max_lon))
        return cursor.fetchall()


def trace_points(mongo_id) -> list:
    """Les points {"lat", "lon"} du tracé d'une rando, lus dans MongoDB ; une liste vide si le tracé manque."""
    MongoUtils.connect()
    trace = MongoUtils.get_collection("gpx_traces").find_one({"_id": ObjectId(mongo_id)}, {"points": 1})
    return trace.get("points", []) if trace else []


def find_same_path_hike(points) -> dict | None:
    """
    La rando en base qui suit le même chemin que ce tracé, ou None. S'il y en a plusieurs, celle qui le recouvre le
    plus. Rend {"id", "name", "city", "share", "start_gap_m", "identical"} : le recouvrement (de 0 à 1), l'écart
    entre les départs en mètres, et si les deux tracés sont identiques (le chargement est alors refusé pour tous).
    """
    if not points:
        return None
    best = None
    for hike in candidate_hikes(points):
        share = overlap_share(points, trace_points(hike["mongo_id"]))
        if share >= DUPLICATE_SHARE and (best is None or share > best["share"]):
            gap_km = haversine_distance_km(points[0]["lat"], points[0]["lon"],
                                           hike["start_latitude"], hike["start_longitude"])
            best = {"id": hike["id"], "name": hike["name"], "city": hike["city"], "share": share,
                    "start_gap_m": round(gap_km * 1000)}
    if best:
        best["identical"] = is_identical(best["share"], best["start_gap_m"])
    return best


def is_identical(share, start_gap_m) -> bool:
    """Dit si deux tracés sont la même rando : recouverts à 99 % ou plus, et partis du même endroit."""
    return share >= IDENTICAL_SHARE and start_gap_m < SAME_START_M


def start_gap_text(gap_m) -> str:
    """
    L'écart entre les deux départs, dit simplement : « qui part du même endroit », « dont le départ est à 60 m »,
    « dont le départ est à 2,6 km » (une virgule, à la française).
    """
    if gap_m < SAME_START_M:
        return "qui part du même endroit"
    if gap_m < 1000:
        return f"dont le départ est à {gap_m} m de celui-ci"
    return f"dont le départ est à {gap_m / 1000:.1f} km de celui-ci".replace(".", ",")


def same_path_reason(hike) -> str:
    """Le motif du refus, pour la page d'ajout : la rando recouverte, sa ville, et où elle part."""
    city = f" ({hike['city']})" if hike.get("city") else ""
    if hike.get("identical"):
        return f"ce tracé est identique à la rando « {hike['name']} »{city}, qui part du même endroit"
    percent = int(hike["share"] * 100)
    return (f"ce tracé recouvre à {percent} % la rando « {hike['name']} »{city}, "
            f"{start_gap_text(hike['start_gap_m'])}")
