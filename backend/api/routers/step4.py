import re
import unicodedata
from datetime import date

from fastapi import APIRouter, Query, Body
from services.commerce_selection_service import CAFE_SERVICES, COMMERCE_SERVICES, SHOP_CATEGORY_LABELS, SHOPS_SHOWN
from services.commerce_selection_service import CAFE as CAFE_SHEET
from services.plan_service import insert_or_update_plan
from services.restaurant_selection_service import (TABLE_CATEGORY_LABELS, TABLES_SHOWN, is_new, is_out_of_season, maps_url,
                                                   season_label)
from etl.transform.transform_osm import DEFAULT_NAME_BY_TYPE
from utils.db_utils import MySQLUtils
from utils.display_utils import enrich_poi, poi_subtitle
from utils.geo_utils import city_commune
from utils.service_utils import POI_FRONTEND_CATEGORY_MAP

router = APIRouter()

MAX_POI_PER_CATEGORY = 10
RESTAURANT_SERVICE = "restaurant"
RESTAURATION_CATEGORY = "restauration"
COMMERCE_CATEGORY = "commerce"
CAFE_CATEGORY = "cafe"
# Les onglets dont l'agent écrit des fiches, et combien de fiches de la commune y sont montrées.
SHEETS_SHOWN = {RESTAURATION_CATEGORY: TABLES_SHOWN, COMMERCE_CATEGORY: SHOPS_SHOWN, CAFE_CATEGORY: SHOPS_SHOWN}
# Toutes les cartes de services ont le bouton Google Maps (7 novembre 2026), sauf le carburant, laissé tel quel.
NO_MAPS_CATEGORIES = ("gasoil",)
# Les noms de secours d'OSM (etl/transform/transform_osm.py) : le lien Google part alors de la position.
GENERIC_NAMES = set(DEFAULT_NAME_BY_TYPE.values())


def postcode_of(address: str | None) -> str | None:
    match = re.search(r"\b(\d{5})\b", address or "")
    return match.group(1) if match else None


def keep_checked(poi_list: list, services: tuple, has_sheet) -> list:
    """
    Là où l'agent d'une chaîne est passé (une de ses fiches a ce code postal), ses services sans fiche ne sont plus
    montrés. has_sheet dit si un lieu a une fiche de cette chaîne : les cafés ne comptent que les fiches de café, sinon une
    commune passée par la version 1 des commerces, sans cafés, perdrait ses cafés d'OSM.
    """
    treated = {postcode_of(poi.get("address")) for poi in poi_list if has_sheet(poi)}
    if not treated:
        return poi_list
    return [poi for poi in poi_list if poi["service_category"] not in services or has_sheet(poi)
            or postcode_of(poi.get("address")) not in treated | {None}]


def keep_checked_commerces(poi_list: list) -> list:
    """
    La règle des restaurants pour les commerces (agents/find_commerces.py) : boulangeries, épiceries, marchés et
    producteurs d'OSM disparaissent là où l'agent a écrit des fiches. Les supermarchés, à part, ne changent pas.
    """
    poi_list = keep_checked(poi_list, COMMERCE_SERVICES, lambda poi: bool(poi.get("commerce_genre")) and poi.get("commerce_categorie") != CAFE_SHEET)
    return keep_checked(poi_list, CAFE_SERVICES, lambda poi: poi.get("commerce_categorie") == CAFE_SHEET)


def keep_checked_restaurants(poi_list: list) -> list:
    """
    Là où l'agent find_restaurants.py est passé, seuls les restaurants qui ont une fiche sont montrés.
    Ailleurs, on garde ceux d'OSM tant que la commune n'est pas traitée : le code postal le dit, car une zone de 5 km
    déborde sur la voisine (les fiches de Plougonvelin faisaient disparaître les restaurants de Locmaria-Plouzané).
    Un restaurant sans adresse lisible n'est gardé que s'il n'y a aucune fiche autour. Les autres services ne changent pas.
    """
    treated = {postcode_of(poi.get("address")) for poi in poi_list if poi["genre"]}
    if not treated:
        return poi_list
    return [poi for poi in poi_list if poi["service_category"] != RESTAURANT_SERVICE or poi["genre"]
            or postcode_of(poi.get("address")) not in treated | {None}]


def town_key(address: str | None) -> str | None:
    """
    La commune d'une adresse, ce qui suit le code postal, sans majuscules, accents ni tirets : « 29810 Lampaul-Plouarzel »
    donne « lampaul plouarzel », et « 5 route de Trézien, 29810 Plouarzel » donne « plouarzel ».
    """
    match = re.search(r"\b\d{5}\s+([^,]+?)\s*$", address or "")
    if not match:
        return None
    plain = unicodedata.normalize("NFKD", match.group(1)).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[-'’]", " ", plain).lower().split())


def is_own_table(poi: dict, city_name: str) -> bool:
    """Une fiche de la commune : celle de son adresse, pas un nom de rue (route de Trézien) ni une voisine (Lampaul-Plouarzel)."""
    return bool(poi.get("genre")) and town_key(poi.get("address")) == town_key(f"00000 {city_name}")


def display_rank(poi: dict, city_name: str) -> tuple:
    """Les fiches de la commune d'abord, puis le plus proche : un café voisin ne prend pas la place d'une table de la commune."""
    return (not is_own_table(poi, city_name), poi["distance_km"])


def order_category(pois: list, category: str, city_name: str) -> list:
    """
    Les MAX_POI_PER_CATEGORY plus proches. Pour la restauration, les TABLES_SHOWN tables de la commune les plus proches du
    spot : la limite de 10 cachait Les Boucaniers et La Balise, et sans limite Brest, cherchée zone par zone, en montrerait
    une centaine. Le tri par distance suffit à donner celles de la zone du spot. Les autres lieux complètent jusqu'à 10.
    Les commerces suivent la même règle, avec SHOPS_SHOWN.
    """
    pois = sorted(pois, key=lambda poi: display_rank(poi, city_name))
    if category not in SHEETS_SHOWN:
        return pois[:MAX_POI_PER_CATEGORY]
    tables = [poi for poi in pois if is_own_table(poi, city_name)][:SHEETS_SHOWN[category]]
    others = [poi for poi in pois if not is_own_table(poi, city_name)]
    return tables + others[:max(0, MAX_POI_PER_CATEGORY - len(tables))]


CATEGORY_LABELS = {**TABLE_CATEGORY_LABELS, **SHOP_CATEGORY_LABELS}
SHEET_FIELDS = ("genre", "pourquoi", "categorie", "registre_depuis")


def sheet_of(poi: dict) -> dict:
    """La fiche du lieu, celle de l'agent restaurants ou celle de l'agent commerces (colonnes commerce_*)."""
    if poi.get("genre") or not poi.get("commerce_genre"):
        return {field: poi.get(field) for field in SHEET_FIELDS}
    return {field: poi.get(f"commerce_{field}") for field in SHEET_FIELDS}


def is_generic_name(name: str | None) -> bool:
    """« Laverie », « Laverie Util », « Toilettes publiques » : un nom de secours, pas celui d'un lieu."""
    return any((name or "").startswith(generic) for generic in GENERIC_NAMES)


def shown_verified(poi: dict, frontend_category: str, sheet: dict) -> int:
    """
    Dans les onglets dont un agent écrit les fiches, « Vérifié » suit la preuve (restaurant_service.set_verified) :
    un lieu d'OSM sans fiche n'a été contrôlé par personne, même si load_poi.py l'a chargé avec verifie = 1.
    Les autres onglets (eau, toilettes...) gardent la valeur de la base.
    """
    if frontend_category in SHEETS_SHOWN and not sheet["genre"]:
        return 0
    return poi["verifie"]


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
    spot_lon: float = Query(None, description="Longitude du spot choisi, utilisée comme point de référence"),
    day_date: date = Query(None, description="Date du jour du voyage (AAAA-MM-JJ) : un lieu fermé en cette saison n'est pas montré")
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
        "SELECT name, commune, latitude, longitude FROM cities WHERE id = %s",
        (city_id,)
    )
    city = cursor.fetchone()
    
    if not city:
        cursor.close()
        MySQLUtils.disconnect(cnx)
        empty = {
            "eau": [], "vidange": [], "gasoil": [], "supermarche": [], "commerce": [],
            "restauration": [], "cafe": [],
            "toilettes": [],
            "hygiene": [], "laverie": [],
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
            p.maps_url AS maps_saisi,
            --
            s.category as service_category,
            s.name as service_name,
            r.genre,
            r.pourquoi,
            r.budget,
            r.jours_fermeture,
            r.distinction,
            r.categorie,
            r.registre_depuis,
            c.genre AS commerce_genre,
            c.pourquoi AS commerce_pourquoi,
            c.categorie AS commerce_categorie,
            c.registre_depuis AS commerce_registre_depuis,
            c.jours,
            p.statut_saison,
            p.mois_ouverture
        FROM poi p
        JOIN poi_service ps ON p.id = ps.poi_id
        JOIN services s ON ps.service_id = s.id
        LEFT JOIN restaurants r ON r.poi_id = p.id
        LEFT JOIN commerces c ON c.poi_id = p.id
        WHERE p.masque = 0
        AND (
            (p.latitude BETWEEN %s AND %s AND p.longitude BETWEEN %s AND %s)
            -- Une commune déborde de la zone : la Pointe Saint-Mathieu est à 5,2 km du centre de Plougonvelin.
            OR ((r.poi_id IS NOT NULL OR c.poi_id IS NOT NULL) AND p.address LIKE %s)
        )
        ORDER BY s.category, p.name ASC
    """

    # Une adresse finit par la commune (« 29810 Plouarzel »), jamais par le lieu-dit (Trézien).
    cursor.execute(query, (min_lat, max_lat, min_lon, max_lon, f"%{city_commune(city)}"))
    poi_list = keep_checked_commerces(keep_checked_restaurants(cursor.fetchall()))

    cursor.close()
    MySQLUtils.disconnect(cnx)
    
    category_mapping = POI_FRONTEND_CATEGORY_MAP

    # Grouper les POI par catégorie
    categorized_poi = {
        "eau": [], "vidange": [], "gasoil": [], "supermarche": [], "commerce": [],
        "restauration": [], "cafe": [],
        "toilettes": [],
        "hygiene": [], "laverie": [],
        "culture": [],
        "urgence": []
    }
    seen_ids = {cat: set() for cat in categorized_poi}

    # Appelée directement (tests), la valeur par défaut est l'objet Query de FastAPI, pas None.
    day = day_date if isinstance(day_date, date) else date.today()
    for poi in poi_list:
        # Un lieu sans position ne peut être ni mesuré ni placé sur la carte : un lieu « position introuvable »
        # validé dans /supervision en est un (Biscuiterie de la Pointe Saint-Mathieu, 7 novembre 2026).
        if poi.get('latitude') is None or poi.get('longitude') is None:
            continue
        if is_out_of_season(poi.get('statut_saison'), poi.get('mois_ouverture'), day):
            continue
        service_cat = poi.get('service_category', '').lower()
        frontend_category = category_mapping.get(service_cat)
        if not frontend_category:
            continue

        poi_id = poi['id']
        if poi_id in seen_ids[frontend_category]:
            continue
        seen_ids[frontend_category].add(poi_id)

        distance_km = haversine_distance_km(ref_lat, ref_lon, poi['latitude'], poi['longitude'])
        sheet = sheet_of(poi)

        categorized_poi[frontend_category].append(enrich_poi({
            "id": poi_id,
            "name": poi['name'],
            # La phrase de l'agent restaurants ou commerces : OSM n'a aucune description pour ces lieux.
            "description": poi['description'] or sheet['pourquoi'],
            "latitude": poi['latitude'],
            "longitude": poi['longitude'],
            "verifie": shown_verified(poi, frontend_category, sheet),
            "image_url": poi['image_url'],
            "url": poi['url'],
            "address": poi['address'],
            "service_type": CATEGORY_LABELS.get(sheet['categorie'], poi['service_name']),
            "distance_km": round(distance_km, 2),
            "from_spot": spot_lat is not None,
            "genre": sheet['genre'],
            "pourquoi": sheet['pourquoi'],
            "budget": poi['budget'],
            "jours_fermeture": poi['jours_fermeture'],
            "distinction": poi['distinction'],
            "categorie": sheet['categorie'],
            # Le jour d'un marché (agents/analyze_commerces.py), lu sur une page acceptée.
            "jours": poi.get('jours'),
            "nouveau": is_new(sheet['registre_depuis']),
            # Le lien Google Maps saisi par un admin dans /supervision passe avant celui que le code fabrique.
            "maps_url": None if frontend_category in NO_MAPS_CATEGORIES else poi.get('maps_saisi') or maps_url(
                poi['name'], poi['address'], poi['latitude'], poi['longitude'], generic=is_generic_name(poi['name'])),
            "statut_saison": poi['statut_saison'],
            "saison_label": season_label(poi['statut_saison'], poi['mois_ouverture']),
            "mois_ouverture": poi['mois_ouverture']
        }))

    # Ne garder que les premiers POI de chaque catégorie
    for category, pois in categorized_poi.items():
        categorized_poi[category] = order_category(pois, category, city_commune(city))

    # Phrases de sous-titre par catégorie, calculées APRÈS la troncature,
    # pour correspondre au nombre réellement affiché.
    categorized_poi["subtitles"] = _build_subtitles(categorized_poi)

    return categorized_poi

@router.put("/update_plan/{plan_id}",summary="Update an existing trip plan with new data.")
def update_plan(plan_id: int, data: dict = Body(...)):
    plan_id = insert_or_update_plan(plan_id, data)
    return {"status": "updated", "plan_id": plan_id, "recap": data}
