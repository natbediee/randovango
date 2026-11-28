from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from api.dependencies import get_current_traveller, require_plan_owner
from api.rate_limit import (CREATE_PLAN_LIMIT, CREATE_PLAN_MESSAGE, DAY_CHOICE_MESSAGE, DAY_CITY_LIMIT,
                            METEO_REFRESH_LIMIT, METEO_REFRESH_MESSAGE, limiter)
from api.trip_limits import DEFAULT_RADIUS_KM, check_day_in_trip, check_radius, check_trip_duration
from utils.logger_util import LoggerUtil
from utils.db_utils import MySQLUtils
from etl.etl_meteo import run_meteo_etl
from etl.etl_carburants import refresh_prices
from etl.load.load_carburants import prices_read_at
from etl.etl_pharmacies import refresh_pharmacies
from etl.load.load_pharmacies import pharmacies_read_at
from api.models.cities import CityList
from utils.meteo_utils import meteo_code_to_picto
from utils.service_utils import POI_FRONTEND_CATEGORY_MAP
from utils.display_utils import enrich_meteo_forecasts, city_stats_labels
from utils.geo_utils import communes_only
from services.pepite_service import start_zone_search
from services.plan_service import owner_columns, set_day_city
from typing import List
from datetime import datetime, timedelta, date
import time
import threading
from utils.paris_time import paris_today

router = APIRouter()
logger = LoggerUtil.get_logger("router")

# Verrou pour empêcher plusieurs rafraîchissements météo globaux en parallèle
meteo_refresh_lock = threading.Lock()
meteo_refresh_in_progress = False


# L'ORDRE DU TOUR MÉTÉO (issue #367)
# Le tour de toutes les villes dure environ une demi-heure (782 villes, 2 secondes entre deux appels). Les villes que
# les voyageurs ont choisies passent donc en premier : d'abord celles des voyages pas encore finis, puis les plus
# choisies, puis toutes les autres, dans l'ordre de la table.
# Un voyage passe par sa ville de départ (trip_plans.city_id) et par la ville de chacun de ses jours (trip_days.city_id).
# UNION, et non UNION ALL, retire les doublons : une ville vue à plusieurs jours d'un même voyage compte une seule fois.
TRIP_CITIES_QUERY = """
    SELECT tp.id AS plan_id, tp.city_id, tp.start_date, tp.duration_days FROM trip_plans tp
    UNION
    SELECT tp.id, td.city_id, tp.start_date, tp.duration_days
    FROM trip_days td JOIN trip_plans tp ON tp.id = td.trip_plan_id
    WHERE td.city_id IS NOT NULL
"""


def trip_last_day(start_date, duration_days) -> date:
    """Le dernier jour d'un voyage : un voyage de 3 jours qui part le 1er finit le 3."""
    return start_date + timedelta(days=duration_days - 1)


def order_cities_for_meteo(cities, trip_cities, today) -> list:
    """
    Range les villes pour le tour météo : celles des voyages pas encore finis d'abord, puis les plus choisies
    (le nombre de voyages qui passent par elles), puis les autres. À égalité, l'ordre de la table est gardé.
    """
    upcoming, choices = set(), {}
    for row in trip_cities:
        choices[row["city_id"]] = choices.get(row["city_id"], 0) + 1
        if trip_last_day(row["start_date"], row["duration_days"]) >= today:
            upcoming.add(row["city_id"])
    # sorted garde l'ordre d'origine à égalité ; False (ville d'un voyage à venir) passe avant True.
    return sorted(cities, key=lambda city: (city["id"] not in upcoming, -choices.get(city["id"], 0)))


def refresh_all_cities_meteo_background():
    """Rafraîchit la météo de toutes les villes en arrière-plan (thread séparé, non bloquant), celles des voyageurs d'abord."""
    global meteo_refresh_in_progress
    try:
        # « with » : la connexion se ferme à la sortie du bloc, même si la requête échoue (issue #206).
        # Elle est rendue avant la boucle météo, qui dure plusieurs minutes.
        with MySQLUtils.open_cursor(dictionary=True) as (cnx, cursor):
            cursor.execute("SELECT id, name, latitude, longitude FROM cities")
            cities = cursor.fetchall()
            cursor.execute(TRIP_CITIES_QUERY)
            trip_cities = cursor.fetchall()
        cities = order_cities_for_meteo(cities, trip_cities, paris_today())

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

# LES PRIX DES CARBURANTS DU JOUR (décision du 11 novembre 2026)
# Au début d'un voyage, comme la météo : si les prix de toutes les stations n'ont pas encore été relus aujourd'hui,
# refresh_prices relit le fichier national de l'État dans un fil à part (gratuit, quelques secondes, sans Overpass).
# La page ne l'attend pas, et un échec la laisse intacte : les anciens prix restent affichés, avec leur date.
# La date vient de sources.lu_le, pas des stations : une station absente du fichier garde sa date ancienne, et une
# commune chargée le matin a des stations du jour sans que les autres soient relues.
# Après un échec, on attend FUEL_RETRY_MINUTES avant de réessayer, pour ne pas relancer le téléchargement à chaque page.
FUEL_RETRY_MINUTES = 60
fuel_refresh_lock = threading.Lock()
fuel_refresh_in_progress = False
fuel_refresh_failed_at = None


def fuel_prices_are_fresh(read_at, today: date) -> bool:
    """Vrai si le dernier rafraîchissement national des prix date d'aujourd'hui (même horloge que l'écriture)."""
    return read_at is not None and read_at.date() == today


def refresh_fuel_prices_background():
    """Rafraîchit les prix de toutes les stations en arrière-plan. Un échec est noté, jamais remonté."""
    global fuel_refresh_in_progress, fuel_refresh_failed_at
    failed = False
    try:
        logger.info("[CARBURANTS-BG] Début du rafraîchissement des prix")
        loaded = refresh_prices()
        if loaded is None:
            failed = True
            logger.error("[CARBURANTS-BG] Fichier de l'État illisible : les anciens prix restent")
        else:
            logger.info(f"[CARBURANTS-BG] Prix rafraîchis pour {loaded} stations")
    except Exception as e:
        failed = True
        logger.error(f"[CARBURANTS-BG] Échec du rafraîchissement des prix, les anciens restent : {e}")
    finally:
        with fuel_refresh_lock:
            fuel_refresh_in_progress = False
            fuel_refresh_failed_at = datetime.now() if failed else None


def start_fuel_prices_refresh() -> bool:
    """Lance le rafraîchissement des prix s'il le faut. Vrai s'il est lancé. Ne lève jamais d'erreur."""
    global fuel_refresh_in_progress
    now = datetime.now()
    try:
        if fuel_prices_are_fresh(prices_read_at(), now.date()):
            return False
    except Exception as e:
        logger.error(f"[CARBURANTS-BG] Date du dernier rafraîchissement illisible, rien n'est lancé : {e}")
        return False
    with fuel_refresh_lock:
        if fuel_refresh_in_progress:
            return False
        if fuel_refresh_failed_at and now - fuel_refresh_failed_at < timedelta(minutes=FUEL_RETRY_MINUTES):
            return False
        fuel_refresh_in_progress = True
    threading.Thread(target=refresh_fuel_prices_background, daemon=True).start()
    return True


# LES PHARMACIES DU JOUR (carte #241)
# Même règle que les prix des carburants : au début d'un voyage, si FINESS n'a pas encore été relu aujourd'hui,
# refresh_pharmacies le relit dans un fil à part (gratuit, 52 Mo, quelques secondes) et repasse toutes les villes.
# Une pharmacie fermée dans FINESS est ainsi masquée au plus tard un jour après sa fermeture, une pharmacie qui ouvre
# est ajoutée. La page ne l'attend pas, et un échec la laisse intacte : les pharmacies déjà en base restent montrées.
# La date vient de sources.lu_le de la source finess. Après un échec, on attend PHARMACY_RETRY_MINUTES.
PHARMACY_RETRY_MINUTES = 60
pharmacy_refresh_lock = threading.Lock()
pharmacy_refresh_in_progress = False
pharmacy_refresh_failed_at = None


def pharmacies_are_fresh(read_at, today: date) -> bool:
    """Vrai si FINESS a déjà été relu en entier aujourd'hui."""
    return read_at is not None and read_at.date() == today


def refresh_pharmacies_background():
    """Relit FINESS et repasse toutes les villes, en arrière-plan. Un échec est noté, jamais remonté."""
    global pharmacy_refresh_in_progress, pharmacy_refresh_failed_at
    failed = False
    try:
        logger.info("[PHARMACIES-BG] Début de la relecture de FINESS")
        loaded = refresh_pharmacies()
        if loaded is None:
            failed = True
            logger.error("[PHARMACIES-BG] Fichier FINESS illisible : les pharmacies déjà en base restent")
        else:
            logger.info(f"[PHARMACIES-BG] FINESS relu : {loaded} pharmacies repassées")
    except Exception as e:
        failed = True
        logger.error(f"[PHARMACIES-BG] Échec de la relecture de FINESS, les pharmacies déjà en base restent : {e}")
    finally:
        with pharmacy_refresh_lock:
            pharmacy_refresh_in_progress = False
            pharmacy_refresh_failed_at = datetime.now() if failed else None


def start_pharmacies_refresh() -> bool:
    """Lance la relecture de FINESS s'il le faut. Vrai si elle est lancée. Ne lève jamais d'erreur."""
    global pharmacy_refresh_in_progress
    now = datetime.now()
    try:
        if pharmacies_are_fresh(pharmacies_read_at(), now.date()):
            return False
    except Exception as e:
        logger.error(f"[PHARMACIES-BG] Date de la dernière relecture illisible, rien n'est lancé : {e}")
        return False
    with pharmacy_refresh_lock:
        if pharmacy_refresh_in_progress:
            return False
        if pharmacy_refresh_failed_at and now - pharmacy_refresh_failed_at < timedelta(minutes=PHARMACY_RETRY_MINUTES):
            return False
        pharmacy_refresh_in_progress = True
    threading.Thread(target=refresh_pharmacies_background, daemon=True).start()
    return True


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

    # Les randos comptées sont celles que l'étape 2 proposera (step2.get_hikes) : près de la ville, ou rangées dans une
    # ville de la même commune (la rando de Locuon, à 6 km du centre de Ploërdut, issue #184). Le OR suit tout le
    # carré : en SQL, AND passe avant OR.
    cursor.execute(f"""
        SELECT c.id AS city_id, COUNT(*) AS cnt
        FROM cities c
        JOIN hikes h {bbox_on("h", "start_latitude", "start_longitude")}
                  OR h.city_id IN (SELECT o.id FROM cities o WHERE o.insee = c.insee)
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
        WHERE s.category IN ({placeholders}) AND p.masque = 0
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
    référencée) - calculée dynamiquement, pas codée en dur, pour suivre l'ajout
    de nouveaux départements sans changement de code.
    """
    # « with » : la connexion se ferme à la sortie du bloc, même si la requête échoue (issue #206).
    with MySQLUtils.open_cursor(dictionary=True) as (cnx, cursor):
        cursor.execute("""
            SELECT MIN(latitude) AS min_lat, MAX(latitude) AS max_lat,
                   MIN(longitude) AS min_lon, MAX(longitude) AS max_lon
            FROM cities
        """)
        return cursor.fetchone()

# LES COMMUNES SEULEMENT (issue #184, décision du 15 novembre 2026). Ranger les services et les spots sous le nom d'un
# lieu-dit en perdait : la station Carrefour de Plouguerneau était introuvable, Plouguerneau n'existant que sous Lilia
# et Tremenac'h. « Où pars-tu » ne propose donc plus que les communes (geo_utils.communes_only). Les randos d'un
# lieu-dit sortent depuis sa commune : l'étape 2 cherche les randos autour du point de départ, pas par ville.


def load_communes(cursor) -> list:
    """Les villes que « Où pars-tu » propose : les communes, sans les lieux-dits, par ordre alphabétique."""
    cursor.execute(f"""
        SELECT id, name, department, region, country, latitude, longitude FROM cities
        WHERE {communes_only()} ORDER BY name ASC
    """)
    return cursor.fetchall()


@router.get("/cities", response_model=List[CityList], summary="Returns the list of cities with statistics and updated weather forecasts.")
async def get_ville_list(
    request: Request,
    distance_km: float = Query(DEFAULT_RADIUS_KM, description="Rayon de recherche en km (25 au plus)")
):
    check_radius(distance_km)   # avant toute lecture en base (issue #263)
    # « with » : la connexion se ferme à la sortie du bloc, même si une requête échoue (issue #206).
    with MySQLUtils.open_cursor(dictionary=True) as (cnx, cursor):
        # Vérification si les données météo J+6 existent (7 jours de prévisions : J+0 à J+6)
        date_j6 = paris_today() + timedelta(days=6)
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

        # Les prix des carburants du jour, en arrière-plan aussi (voir start_fuel_prices_refresh).
        start_fuel_prices_refresh()
        # Les pharmacies du jour (fermetures et ouvertures de FINESS), en arrière-plan aussi (voir start_pharmacies_refresh).
        start_pharmacies_refresh()

        cities = load_communes(cursor)

        # Stats de toutes les villes en une poignée de requêtes agrégées (voir get_all_city_stats)
        # au lieu d'une boucle de 6 requêtes par ville.
        all_stats = get_all_city_stats(cursor, cities, distance_km)

        # Météo de toutes les villes en une seule requête, regroupée ensuite par ville en Python.
        city_ids = [c["id"] for c in cities]
        meteo_by_city = {cid: [] for cid in city_ids}
        if city_ids:
            placeholders = ",".join(["%s"] * len(city_ids))
            cursor.execute(
                f"SELECT * FROM weather WHERE city_id IN ({placeholders}) AND DATE >= %s ORDER BY city_id, date ASC",
                (*city_ids, paris_today())
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

        # Champs prêts à afficher (libellés des stats, entêtes et conseils météo)
        # calculés en Python : le frontend n'a plus qu'à les insérer dans la page.
        for row in cities:
            row["stats"] = all_stats[row["id"]]
            row["stats_labels"] = city_stats_labels(all_stats[row["id"]])
            row["meteo"] = enrich_meteo_forecasts(meteo_by_city[row["id"]])

    return cities


# Le message d'une création de voyage qui plante (issue #377) : le texte de l'erreur reste dans le journal du serveur.
CREATE_PLAN_FAILED_MESSAGE = "Ton voyage n'a pas pu être créé. Réessaie dans quelques instants."


@router.post("/create_plan", summary="Create a new trip plan with empty days (owner taken from the token).")
# La ville choisie lance les recherches de Vany (carte #21).
@limiter.limit(CREATE_PLAN_LIMIT, error_message=CREATE_PLAN_MESSAGE)
def create_plan(
    request: Request,
    city_id: int = Body(...),
    duration_days: int = Body(...),
    start_date: date = Body(None),
    traveller: dict = Depends(get_current_traveller),
):
    """Créer un nouveau plan (trip_plans + jours vides pour l'étape 1)"""
    # Le propriétaire du plan vient du jeton du cookie, jamais du corps de la requête (carte #104) :
    # avant, le navigateur envoyait lui-même user_id ou user_token, et pouvait créer un plan au nom
    # d'un autre. Un compte possède le plan par son user_id, un invité par son identifiant invité.
    user_id_to_insert, user_token_to_insert = owner_columns(traveller)
    # Garde-fous : une durée valide et une ville qui existe réellement. Sans ces
    # contrôles, une ville absente déclenche une violation de contrainte FK que
    # l'on renvoyait en 500 opaque au frontend (« Erreur lors de la création du
    # plan : 500 »). On préfère un 400 explicite et actionnable.
    if duration_days is None or duration_days < 1:
        raise HTTPException(status_code=400, detail="La durée du séjour doit être d'au moins 1 jour.")
    # Et 7 jours au plus, ceux de l'offre gratuite : sinon une seule requête écrirait des milliers de jours (issue #263).
    check_trip_duration(duration_days)
    try:
        # « with » : la connexion se ferme à la sortie du bloc, même si une requête échoue (issue #206).
        with MySQLUtils.open_cursor() as (cnx, cursor):
            cursor.execute("SELECT 1 FROM cities WHERE id = %s", (city_id,))
            if cursor.fetchone() is None:
                raise HTTPException(status_code=400, detail=f"Ville introuvable (id={city_id}). Choisis une ville dans la liste.")
            try:
                plan_id = insert_plan_with_days(cursor, start_date or paris_today(), duration_days, city_id,
                                                user_token_to_insert, user_id_to_insert)
                cnx.commit()
            except Exception:
                # Une écriture a échoué : on annule le plan à moitié écrit, avant que le with ferme la connexion.
                cnx.rollback()
                raise
        # La ville est choisie : Vany commence à chercher ses pépites
        # pendant que l'utilisateur choisit sa rando et son spot.
        start_zone_search(plan_id, 1)
        return {"plan_id": plan_id, "message": "Plan créé avec succès."}
    except HTTPException:
        # Erreur client déjà formée (ville introuvable, etc.) : la laisser passer
        # telle quelle plutôt que de la ré-emballer en 500.
        raise
    except Exception as e:
        # Le texte de l'erreur peut montrer la base, une requête ou un chemin : il part dans le journal du serveur,
        # et le voyageur reçoit un message simple (issue #377, comme les routes GPX et météo).
        logger.error(f"Échec de la création d'un voyage (ville {city_id}, {duration_days} jours) : {e}")
        raise HTTPException(status_code=500, detail=CREATE_PLAN_FAILED_MESSAGE)


def insert_plan_with_days(cursor, plan_start_date, duration_days, city_id, user_token, user_id) -> int:
    """Écrit le plan (trip_plans) et ses jours vides (trip_days), tous dans la ville de départ ; rend l'id du plan."""
    insert_plan = """
        INSERT INTO trip_plans (start_date, duration_days, city_id, user_token, user_id, created_at)
        VALUES (%s, %s, %s, %s, %s, NOW())
    """
    cursor.execute(insert_plan, (plan_start_date, duration_days, city_id, user_token, user_id))
    plan_id = cursor.lastrowid
    insert_day = """
        INSERT INTO trip_days (trip_plan_id, day_number, hike_id, spot_id, city_id)
        VALUES (%s, %s, NULL, NULL, %s)
    """
    for day_num in range(1, duration_days + 1):
        cursor.execute(insert_day, (plan_id, day_num, city_id))
    return plan_id


@router.put("/update_day_city/{plan_id}", summary="Set (or change) the city for a given day of the trip.",
            dependencies=[Depends(require_plan_owner)])
# Chaque ville choisie lance les recherches de Vany (carte #21).
@limiter.limit(DAY_CITY_LIMIT, error_message=DAY_CHOICE_MESSAGE)
def update_day_city(request: Request, plan_id: int, data: dict = Body(...)):
    """Fixe la ville d'un jour du séjour, appelé à chaque transition de jour depuis /results."""
    day_number = data.get("day_number")
    city_id = data.get("city_id")
    if day_number is None or city_id is None:
        raise HTTPException(status_code=400, detail="day_number et city_id sont requis.")
    # Un jour hors du séjour est refusé avant d'écrire et avant de lancer Vany (issue #263).
    check_day_in_trip(plan_id, day_number)
    set_day_city(plan_id, day_number, city_id)
    start_zone_search(plan_id, day_number)   # voir create_plan
    return {"status": "updated", "plan_id": plan_id, "day_number": day_number, "city_id": city_id}


# Le message d'une actualisation météo qui plante (issue #213) : le texte de l'erreur reste dans le journal du serveur.
METEO_REFRESH_FAILED_MESSAGE = "La météo de cette ville n'a pas pu être actualisée. Réessaie plus tard."


@router.get("/refresh-meteo/{city_id}", summary="Refresh weather data for a specific city")
# Chaque appel fait appeler Open-Meteo : plafonné par voyageur (issue #213, docs/plafonds.md).
@limiter.limit(METEO_REFRESH_LIMIT, error_message=METEO_REFRESH_MESSAGE)
def refresh_city_meteo(request: Request, city_id: int):
    """
    Lance l'ETL météo d'une ville, quand ses prévisions manquent ou n'atteignent plus J+6, et rend les nouvelles.

    Une route « def », et non « async def » (issue #367, même piège que l'issue #328) : elle attend Open-Meteo et
    la base sans rendre la main. En « async def », tout le serveur attendait avec elle, environ 1 seconde, jusqu'à
    10 si Open-Meteo ne répond pas. Une route « def », FastAPI la fait tourner à part, et les autres pages répondent.
    """
    try:
        # « with » : la connexion se ferme à la sortie du bloc, même si une requête échoue (issue #206).
        with MySQLUtils.open_cursor(dictionary=True) as (cnx, cursor):
            # Récupérer le nom et les coordonnées de la ville
            cursor.execute("SELECT name, latitude, longitude FROM cities WHERE id = %s", (city_id,))
            result = cursor.fetchone()

            if not result:
                raise HTTPException(status_code=404, detail="Ville non trouvée")

            city_name = result['name']
            logger.info(f"[REFRESH] Lancement ETL météo pour la ville : {city_name}")

            # Lancer l'ETL météo avec les coordonnées DB (évite l'appel Nominatim). Son résultat reste ici : il peut
            # porter le texte d'une erreur interne, que le navigateur n'a pas à voir (issue #213).
            run_meteo_etl(city_name, result['latitude'], result['longitude'])

            # Récupérer les prévisions météo fraîchement créées
            cursor.execute("SELECT * FROM weather WHERE city_id = %s AND DATE >= %s ORDER BY date ASC", (city_id, paris_today()))
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

        # Même enrichissement que /cities : le frontend remplace son cache météo
        # tel quel, la forme des deux réponses doit donc être identique.
        return {
            "city_id": city_id,
            "city_name": city_name,
            "meteo": enrich_meteo_forecasts(forecasts),
            "message": f"Données météo actualisées pour {city_name}"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors du refresh météo pour city_id {city_id}: {e}")
        # Le texte de l'erreur part dans le journal ci-dessus, jamais au navigateur (issue #213).
        raise HTTPException(status_code=500, detail=METEO_REFRESH_FAILED_MESSAGE)


