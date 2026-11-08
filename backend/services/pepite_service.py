"""
Les pépites de Vany : 2 ou 3 idées autour de la journée planifiée, ce qu'un
habitant conseillerait à un ami de passage (un lieu à ne pas rater, un coucher de
soleil, un fest-noz ce soir-là...). Elles sont présentées à l'étape 5, après les
services ; l'utilisateur en ajoute autant qu'il veut à sa journée.

LE PRINCIPE : LE CODE DÉCIDE DE CE QUI EST POSSIBLE, L'IA DE CE QUI EST LE MIEUX
Quatre agents, chacun à sa place :
    - agents/discover_places.py : trouve les lieux en accès libre d'une ville, une fois
      pour toutes, à l'import par l'ETL (search_city_places) ou par le rattrapage
      (search_missing_places) ;
    - agents/find_pepites.py : trouve l'agenda (événements, marchés, sorties, lieux à
      horaires) au choix de la ville, pour les dates du séjour ;
    - agents/choose_pepites.py : choisit, parmi les idées possibles ce jour-là, les
      meilleures pour CETTE journée, avec une phrase pour chacune ;
    - agents/locate_pepites.py : retrouve la position exacte des lieux que le code n'a
      pas su recaler, en recopiant les coordonnées d'une page qu'il cite (relocate).
Les deux premiers décrivent chaque idée avec des champs précis (catégorie, lieu et
adresse, dates, jours d'ouverture, créneau, durée, en extérieur ou non). Ici, sans IA :
    1. on retrouve la vraie position de chaque idée (locate) ;
    2. on cherche en base les idées déjà trouvées autour du spot et de la rando ;
    3. on garde celles qui sont possibles CE jour-là (date, temps libre, météo, pas
       sur le parcours d'une rando du séjour) ;
    4. on soumet les plus proches au choix de Vany (ou on les prend telles quelles
       s'il ne répond pas) ;
    5. on n'appelle les agents de recherche que s'il manque des idées et qu'une
       recherche récente manque pour cette zone (ou si le séjour a déjà utilisé les
       idées de la zone : recherche complémentaire, une fois par jour).
Les idées qui ne sont pas montrées restent en base pour les jours suivants : une idée
trouvée pour un voyageur sert aussi à tous ceux qui passent dans la zone.

« EN CHEMIN » : un lieu ou un point de vue à moins de 400 m du tracé GPX d'une rando
n'est pas une sortie de plus, on le voit en marchant. Il n'est donc jamais proposé
comme pépite ; il devient un conseil pour le jour de cette rando (fetch_trail_tips).
Une activité, un événement ou un marché sur le parcours (concert au bourg) reste une
pépite : on ne le fait pas en passant.

LES TABLES (créées par db_init/db_randovango.py)
    - pepites           : les idées trouvées par l'agent
    - pepite_recherches : les recherches déjà faites (type, zone, période, version
                          des consignes), pour ne pas rappeler l'agent quand il
                          n'a rien trouvé
    - trip_day_pepites  : les idées proposées pour un jour du séjour, avec leur
                          statut : 'proposee', 'choisie' (ajoutée à la journée, il
                          peut y en avoir plusieurs) ou 'retiree' (choisie, puis
                          devenue incompatible après une modification du jour),
                          la phrase de Vany et son coup de cœur

LES RECHERCHES DU PARCOURS SONT LANCÉES EN TÂCHE DE FOND :
    - dès que la VILLE du jour est choisie (étape 1) : l'agenda autour du centre-ville,
      et les lieux s'ils n'ont pas encore été cherchés (start_zone_search). Une
      recherche web prend souvent plusieurs minutes : elle tourne pendant que
      l'utilisateur choisit sa rando, son spot et ses services ;
    - quand le SPOT est choisi (étape 3) : préparation du jour avec ce qui est déjà en
      base, en quelques secondes (start_preparation) ; le voyageur n'attend pas l'agenda ;
    - puis, sans bloquer personne, second temps (complete_day) : quand les recherches sont
      finies, les idées qu'elles apportent s'ajoutent, et la barre du bas le signale
      (day_news) si le voyageur a quitté l'étape 5.
La page de l'étape 5 interroge régulièrement l'API (get_day_state) pendant ce temps.
"""
import json
import re
import threading
import unicodedata
from datetime import date, datetime, timedelta

from services.map_service import fetch_hike_trace
from utils.db_utils import MySQLUtils
from utils.display_utils import (HIKE_START_H, pepite_news_text, pepite_section, pepite_day_texts, pepite_display, pepite_nothing_texts, spot_name_label,
                                 trail_tip_display)
from utils.geo_utils import geocode_address_ban, get_bounding_box, haversine_distance_km
from utils.logger_util import LoggerUtil
from utils.meteo_utils import meteo_code_to_picto, sunset_time

logger = LoggerUtil.get_logger("pepite_service")


# --- Réglages ----------------------------------------------------------------

# Nombre d'idées proposées pour un jour, par section (display_utils.pepite_section). Le
# même pour tous : que le voyageur attende l'agenda ou non, il finit avec les mêmes idées.
MAX_IDEAS = {"saison": 3, "sejour": 2}
POOL_SIZE = 8          # idées possibles, les plus proches, parmi lesquelles Vany choisit
RADIUS_KM = 10         # autour du spot OU du départ de la rando
NOTE_MIN = 7           # note minimale (sur 10) : "un bon conseil d'habitant"

# Une idée qui peut changer (activité, événement, marché, producteur) est
# revérifiée par une nouvelle recherche au-delà de ce délai. Un lieu permanent
# (monument, site naturel) ne l'est jamais.
FRESH_DAYS = 30
# Durée de validité d'une recherche : l'agenda change, les lieux beaucoup moins.
# Une recherche des lieux est refaite au bout d'un an, pour en trouver de nouveaux.
SEARCH_FRESH_DAYS = {"lieux": 365, "agenda": FRESH_DAYS}

# Journée type : départ de la rando à 9 h (display_utils.HIKE_START_H, affiché au
# voyageur). Une visite en journée doit tenir avant 18 h (fermeture des lieux), une
# idée accessible à toute heure avant 21 h.
DAY_START_H = HIKE_START_H
DAY_END_H = 18
EVENING_END_H = 21
# Une activité à heure fixe (départ d'un bateau, visite guidée) doit commencer au
# moins un quart d'heure après la fin de la rando, le temps de s'y rendre.
TRAVEL_MARGIN_H = 0.25

# Les prévisions météo ne sont fiables qu'à 7 jours.
FORECAST_DAYS = 7
BAD_WEATHER = {"rain", "storm", "snow"}   # pictos de utils/meteo_utils.py

# Classement : les idées les plus proches du spot ou de la rando d'abord. Un
# événement (il n'a lieu que ce jour-là) compte comme s'il était 3 km plus près.
EVENT_HEAD_START_KM = 3

# « En chemin » : à moins de 400 m du tracé d'une rando, un lieu ou un point de vue
# se voit en marchant (l'agent place les lieux de façon approchée, d'où la marge).
# On en montre 4 au plus, dans l'ordre de la marche.
TRAIL_KM = 0.4
TRAIL_CATEGORIES = ("lieu", "point_de_vue")
MAX_TRAIL_TIPS = 4

# Position d'une idée : l'agent l'estime de mémoire, souvent à plusieurs centaines
# de mètres près (un cinéma s'est retrouvé en mer). Le code cherche la vraie
# position du lieu dans la base ETL jusqu'à 5 km de cette estimation (voir locate).
LOCATE_KM = 5


# =============================================================================
# 2. LE CONTEXTE DE LA JOURNÉE
# =============================================================================

def load_day_context(cursor, plan_id: int, day_number: int) -> dict | None:
    """
    Tout ce qu'il faut savoir sur un jour pour lui choisir des idées : sa date, sa
    ville, son spot, sa rando (départ et durée), les randos du séjour et la météo.
    Le spot peut manquer (recherche lancée dès le choix de la ville) : "has_spot"
    le dit, et le centre-ville sert alors de point de référence.
    """
    cursor.execute("""
        SELECT td.id AS trip_day_id, td.trip_plan_id AS plan_id, td.day_number, tp.start_date, tp.duration_days,
               COALESCE(td.city_id, tp.city_id) AS city_id, c.name AS city_name,
               c.latitude AS city_latitude, c.longitude AS city_longitude,
               h.name AS hike_name, h.estimated_duration_h AS hike_duration_h, h.mongo_id AS hike_mongo_id,
               h.start_latitude AS hike_latitude, h.start_longitude AS hike_longitude,
               s.latitude AS spot_latitude, s.longitude AS spot_longitude,
               s.place_label, s.city_label, s.name AS spot_raw_name, s.type AS spot_type
        FROM trip_days td
        JOIN trip_plans tp ON tp.id = td.trip_plan_id
        LEFT JOIN cities c ON c.id = COALESCE(td.city_id, tp.city_id)
        LEFT JOIN hikes h ON h.id = td.hike_id
        LEFT JOIN spots s ON s.id = td.spot_id
        WHERE td.trip_plan_id = %s AND td.day_number = %s
    """, (plan_id, day_number))
    day = cursor.fetchone()
    if not day:
        return None

    day["day_date"] = day["start_date"] + timedelta(days=day_number - 1)
    # Dernier jour du séjour : l'agent cherche pour toute la période restante.
    day["trip_end"] = day["start_date"] + timedelta(days=max(day.pop("duration_days"), day_number) - 1)
    day["spot_name"] = spot_name_label(day.pop("place_label"), day.pop("city_label"),
                                       day.pop("spot_raw_name"), day.pop("spot_type"))
    day["hike_duration_h"] = day["hike_duration_h"] or 0
    day["has_spot"] = day["spot_latitude"] is not None

    # Points de référence : le spot, et le départ de la rando s'il y en a une ;
    # le centre-ville tant que le spot n'est pas choisi.
    if day["has_spot"]:
        day["points"] = [(day["spot_latitude"], day["spot_longitude"])]
        if day["hike_latitude"] is not None:
            day["points"].append((day["hike_latitude"], day["hike_longitude"]))
    else:
        day["points"] = [(day["city_latitude"], day["city_longitude"])]

    # Les randos de tout le séjour : leurs noms pour l'agent, leurs tracés pour ne pas
    # proposer comme pépite ce qu'on voit déjà en marchant.
    cursor.execute("""
        SELECT DISTINCT h.name, h.mongo_id FROM trip_days td JOIN hikes h ON h.id = td.hike_id
        WHERE td.trip_plan_id = %s
    """, (day["plan_id"],))
    hikes = cursor.fetchall()
    day["trip_hikes"] = [row["name"] for row in hikes]
    day["trip_traces"] = [hike_trace(row["mongo_id"]) for row in hikes]

    # Météo : seulement si la journée est dans les 7 prochains jours. Sinon
    # "weather_picto" reste None et les idées en extérieur seront à revérifier.
    # Le détail ("weather") sert au choix de Vany (choose_pepites).
    day["weather_picto"] = day["weather"] = None
    if 0 <= (day["day_date"] - date.today()).days <= FORECAST_DAYS:
        cursor.execute(
            "SELECT weather_code, temp_min_c, temp_max_c, precipitation_mm, wind_max_kmh FROM weather"
            " WHERE city_id = %s AND date = %s ORDER BY id DESC LIMIT 1",
            (day["city_id"], day["day_date"]),
        )
        row = cursor.fetchone()
        if row:
            day["weather_picto"] = meteo_code_to_picto(row["weather_code"])
            day["weather"] = row | {"picto": day["weather_picto"]}
    day["free_time_h"] = free_time_h(day["hike_duration_h"])
    day["sunset"] = sunset_time(day["day_date"], *day["points"][0])
    return day


def free_time_h(hike_duration_h: float, day_end_h: int = DAY_END_H) -> float:
    """Heures libres après la rando, avant `day_end_h` (jamais négatif)."""
    return max(0, day_end_h - DAY_START_H - hike_duration_h)


# =============================================================================
# 3. LES FILTRES ET LE SCORE (sans IA)
# =============================================================================

def is_valid_on(pepite: dict, day: date) -> bool:
    """L'idée existe-t-elle ce jour-là ? (dates d'un événement, jours d'un marché)"""
    if pepite.get("date_debut") and day < pepite["date_debut"]:
        return False
    if pepite.get("date_fin") and day > pepite["date_fin"]:
        return False
    weekdays = pepite.get("jours_semaine") or []   # 0 = lundi ... 6 = dimanche
    return not weekdays or day.weekday() in weekdays


def is_fresh(pepite: dict, now: datetime) -> bool:
    """Un lieu permanent est toujours valable ; le reste doit avoir été vu récemment."""
    return bool(pepite.get("permanent")) or pepite["verified_at"] >= now - timedelta(days=FRESH_DAYS)


def fits_time(pepite: dict, hike_duration_h: float) -> bool:
    """
    L'idée tient-elle dans la journée, avec la rando ?
      - une heure de début fixe (13.25 = 13 h 15) doit tomber après la rando partie à 9 h,
        ou laisser le temps de faire la rando après elle, avant 18 h ;
      - 'soiree'  : après 18 h (fest-noz, concert), la rando ne gêne pas ;
      - 'journee' : lieu à horaires d'ouverture, il faut finir avant 18 h ;
      - 'libre'   : accessible à toute heure (point de vue, plage), avant 21 h.
    """
    duration = pepite.get("duree_h") or 0
    start = pepite.get("heure_debut")
    if start is not None:
        after_the_hike = start >= DAY_START_H + hike_duration_h + TRAVEL_MARGIN_H
        hike_afterwards = start + duration + TRAVEL_MARGIN_H + hike_duration_h <= DAY_END_H
        if not (after_the_hike or hike_afterwards):
            return False
    if pepite["creneau"] == "soiree":
        return True
    day_end = DAY_END_H if pepite["creneau"] == "journee" else EVENING_END_H
    return duration <= free_time_h(hike_duration_h, day_end)


def fits_weather(pepite: dict, weather_picto: str | None) -> bool:
    """Une idée en extérieur est écartée s'il est prévu de la pluie, de l'orage ou de la neige."""
    return not (pepite.get("exterieur") and weather_picto in BAD_WEATHER)


def distance_km(pepite: dict, points: list) -> float:
    """Distance au point de référence le plus proche (spot ou départ de la rando)."""
    return min(haversine_distance_km(lat, lon, pepite["latitude"], pepite["longitude"]) for lat, lon in points)


_traces = {}   # mongo_id -> points (lat, lon) : un tracé GPX ne change pas, on le garde


def hike_trace(mongo_id: str | None) -> list:
    """Points (latitude, longitude) du tracé GPX d'une rando (MongoDB), gardés en mémoire."""
    if mongo_id not in _traces:
        points = [(lat, lon) for lon, lat in fetch_hike_trace(mongo_id)]
        if not points:      # pas de tracé, ou MongoDB injoignable : on réessaiera
            return []
        _traces[mongo_id] = points
    return _traces[mongo_id]


def trace_position(pepite: dict, trace: list) -> int | None:
    """
    Rang du point du tracé le plus proche de l'idée si elle est à moins de 400 m du
    tracé, None sinon. Seuls les points du carré de 400 m autour de l'idée sont mesurés.
    """
    lat, lon = pepite["latitude"], pepite["longitude"]
    min_lat, min_lon, max_lat, max_lon = get_bounding_box(lat, lon, TRAIL_KM)
    near = [(haversine_distance_km(lat, lon, p_lat, p_lon), rank) for rank, (p_lat, p_lon) in enumerate(trace)
            if min_lat <= p_lat <= max_lat and min_lon <= p_lon <= max_lon]
    distance, rank = min(near, default=(None, None))
    return rank if distance is not None and distance <= TRAIL_KM else None


def on_trip_hike(pepite: dict, traces: list) -> bool:
    """Est-ce un lieu ou un point de vue qu'on voit en marchant sur une rando du séjour ?"""
    return pepite["categorie"] in TRAIL_CATEGORIES and any(trace_position(pepite, t) is not None for t in traces)


def closeness(pepite: dict, distance: float) -> float:
    """Clé de classement (plus petit = montré d'abord) : la distance, moins 3 km pour un événement."""
    return distance - (EVENT_HEAD_START_KM if pepite["categorie"] == "evenement" else 0)


def evaluate(pepite: dict, day: dict, now: datetime = None) -> dict | None:
    """
    Renvoie l'idée complétée (distance, classement, météo à revérifier) si elle
    convient à cette journée, None sinon.
    """
    now = now or datetime.now()
    distance = distance_km(pepite, day["points"])
    if (distance > RADIUS_KM
            or (pepite.get("note") or 0) < NOTE_MIN
            or not is_valid_on(pepite, day["day_date"])
            or not is_fresh(pepite, now)
            or not fits_time(pepite, day["hike_duration_h"])
            or not fits_weather(pepite, day["weather_picto"])
            or on_trip_hike(pepite, day.get("trip_traces", []))):
        return None
    return {
        **pepite,
        "distance_km": round(distance, 1),
        "closeness": closeness(pepite, distance),
        # Pas de prévision (journée à plus de 7 jours) : à revérifier la veille.
        "meteo_a_verifier": bool(pepite.get("exterieur")) and day["weather_picto"] is None,
    }


# =============================================================================
# 4. LECTURE ET ÉCRITURE EN BASE
# =============================================================================

def _read_pepite_row(row: dict) -> dict:
    """Les colonnes JSON arrivent en texte depuis MySQL : on les relit en listes."""
    for column in ("jours_semaine", "sources", "themes"):
        if isinstance(row.get(column), str):
            row[column] = json.loads(row[column])
    return row


def find_candidates(cursor, day: dict) -> list:
    """Idées déjà en base dans la zone (rectangle englobant le spot et la rando)."""
    boxes = [get_bounding_box(lat, lon, RADIUS_KM) for lat, lon in day["points"]]
    cursor.execute(
        "SELECT * FROM pepites WHERE latitude BETWEEN %s AND %s AND longitude BETWEEN %s AND %s",
        (min(b[0] for b in boxes), max(b[2] for b in boxes), min(b[1] for b in boxes), max(b[3] for b in boxes)),
    )
    return [_read_pepite_row(row) for row in cursor.fetchall()]


def day_links(cursor, trip_day_id: int) -> list:
    """Les idées liées à ce jour, avec leur statut ('proposee', 'choisie', 'retiree')."""
    cursor.execute("""
        SELECT p.*, tdp.statut, tdp.pourquoi, tdp.moment, tdp.coup_de_coeur, tdp.vue FROM trip_day_pepites tdp
        JOIN pepites p ON p.id = tdp.pepite_id
        WHERE tdp.trip_day_id = %s
    """, (trip_day_id,))
    return [_read_pepite_row(row) for row in cursor.fetchall()]


def ids_used_elsewhere(cursor, day: dict) -> set:
    """Idées déjà proposées les AUTRES jours du séjour : on ne repropose pas la même chose."""
    cursor.execute("""
        SELECT tdp.pepite_id FROM trip_day_pepites tdp
        JOIN trip_days td ON td.id = tdp.trip_day_id
        WHERE td.trip_plan_id = %s AND td.id <> %s
    """, (day["plan_id"], day["trip_day_id"]))
    return {row["pepite_id"] for row in cursor.fetchall()}


# Une idée à moins de 200 m d'une pépite ajoutée un autre jour est sur le même site :
# ce n'est pas une sortie de plus (la pointe Saint-Mathieu proposée le lundi, à 74 m du
# Mémorial des marins visité le dimanche soir).
SAME_SITE_KM = 0.2


def program_elsewhere(cursor, day: dict) -> list:
    """
    Les pépites AJOUTÉES les autres jours du séjour, avec leur date et leur distance au
    centre de la journée : le code écarte les idées sur le même site (same_site_as), et
    Vany voit le programme du séjour pour varier d'un jour à l'autre.
    """
    cursor.execute("""
        SELECT td.day_number, p.nom, p.latitude, p.longitude FROM trip_day_pepites tdp
        JOIN trip_days td ON td.id = tdp.trip_day_id
        JOIN pepites p ON p.id = tdp.pepite_id
        WHERE td.trip_plan_id = %s AND td.id <> %s AND tdp.statut = 'choisie'
        ORDER BY td.day_number
    """, (day["plan_id"], day["trip_day_id"]))
    center = day["points"][0]
    return [{"nom": row["nom"], "latitude": row["latitude"], "longitude": row["longitude"],
             "day_date": day["start_date"] + timedelta(days=row["day_number"] - 1),
             "distance_km": haversine_distance_km(*center, row["latitude"], row["longitude"])}
            for row in cursor.fetchall()]


def same_site_as(idea: dict, program: list) -> bool:
    """L'idée est-elle sur le site d'une pépite déjà au programme d'un autre jour ?"""
    return any(haversine_distance_km(idea["latitude"], idea["longitude"], p["latitude"], p["longitude"])
               < SAME_SITE_KM for p in program)


def recent_search_exists(cursor, day: dict, mode: str, prompt_version: int = 0) -> bool:
    """
    Une recherche récente de ce type ("lieux" ou "agenda") couvre-t-elle déjà cette
    zone (et, pour l'agenda, cette date) ? Une recherche faite avec des consignes
    plus anciennes que `prompt_version` ne compte pas.
    """
    lat, lon = day["points"][0]
    min_lat, min_lon, max_lat, max_lon = get_bounding_box(lat, lon, RADIUS_KM / 2)
    # Les lieux ne dépendent pas de la date : la période de la recherche ne compte pas.
    period = "AND jour <= %(day)s AND jour_fin >= %(day)s" if mode == "agenda" else ""
    cursor.execute(f"""
        SELECT 1 FROM pepite_recherches
        WHERE type = %(mode)s {period} AND searched_at >= %(since)s AND prompt_version >= %(version)s
          AND latitude BETWEEN %(min_lat)s AND %(max_lat)s AND longitude BETWEEN %(min_lon)s AND %(max_lon)s
        LIMIT 1
    """, {"mode": mode, "day": day.get("day_date"), "version": prompt_version,
          "since": datetime.now() - timedelta(days=SEARCH_FRESH_DAYS[mode]),
          "min_lat": min_lat, "max_lat": max_lat, "min_lon": min_lon, "max_lon": max_lon})
    return cursor.fetchone() is not None


def prompt_version(mode: str) -> int:
    """Version actuelle des consignes de l'agent qui fait ce type de recherche."""
    # Import ici et non en haut du fichier : les agents importent eux-mêmes ce module.
    if mode == "lieux":
        from agents.discover_places import PLACES_PROMPT_VERSION
        return PLACES_PROMPT_VERSION
    from agents.find_pepites import AGENDA_PROMPT_VERSION
    return AGENDA_PROMPT_VERSION


def missing_searches(cursor, day: dict) -> list:
    """Les recherches à lancer pour cette zone : l'agenda d'abord (l'utilisateur l'attend)."""
    return [mode for mode in ("agenda", "lieux") if not recent_search_exists(cursor, day, mode, prompt_version(mode))]


def complementary_search_done(cursor, trip_day_id: int) -> bool:
    """Une recherche complémentaire a-t-elle déjà été faite pour ce jour ?"""
    cursor.execute("SELECT 1 FROM pepite_recherches WHERE trip_day_id = %s AND searched_at >= %s LIMIT 1",
                   (trip_day_id, datetime.now() - timedelta(days=FRESH_DAYS)))
    return cursor.fetchone() is not None


def record_search(cursor, day: dict, mode: str, found: int, prompt_version: int, trip_day_id: int = None) -> None:
    """
    Enregistre une recherche. L'agenda couvre le jour préparé et les jours suivants
    du séjour ; les lieux, sans date, sont datés du jour de la recherche.
    `trip_day_id` n'est donné que pour une recherche complémentaire.
    """
    lat, lon = day["points"][0]
    first, last = (day["day_date"], day["trip_end"]) if mode == "agenda" else (date.today(), date.today())
    cursor.execute(
        "INSERT INTO pepite_recherches (latitude, longitude, jour, jour_fin, searched_at, nb_trouvees, type,"
        " prompt_version, trip_day_id) VALUES (%s, %s, %s, %s, NOW(), %s, %s, %s, %s)",
        (lat, lon, first, last, found, mode, prompt_version, trip_day_id),
    )


LIGATURES = str.maketrans({"œ": "oe", "Œ": "OE", "æ": "ae", "Æ": "AE", "ß": "ss"})


def name_key(name: str) -> str:
    """
    Nom comparable : minuscules, sans accents ni ponctuation (« Cinéma Le Dauphin » -> "cinema le dauphin"). Les
    ligatures s'écrivent en deux lettres, comme au registre : « Bœuf » -> "boeuf" (8 novembre 2026, la lettre « œ » était
    effacée et « Au Bœuf Charolais » ne retrouvait plus « AU BOEUF CHAROLAIS »).
    """
    name = (name or "").translate(LIGATURES)
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return " ".join(re.findall(r"[a-z0-9]+", ascii_name))


# Mots qui disent ce qu'est un lieu, pas lequel : la base ETL contient des POI nommés
# seulement « Lavoir » (27), « Point de vue » ou « Calvaire », qu'il ne faut pas
# prendre pour « Point de vue de la pointe de Kastell Ac'h ».
GENERIC_WORDS = set("""
allee couverte menhir menhirs dolmen calvaire chapelle eglise lavoir croix tumulus fontaine moulin
phare point vue plage pointe port ile anse crique cairn tour chateau ruines manoir musee fort
belvedere site archeologique table orientation parking
de du des la le les l d a au aux et en sur
""".split())


def is_generic(key: str) -> bool:
    """Le nom (déjà passé par name_key) n'a-t-il que des mots génériques ?"""
    return all(word in GENERIC_WORDS for word in key.split())


def match_poi(place: str, latitude: float, longitude: float, pois: list) -> dict | None:
    """
    Le POI de la base ETL qui porte le nom du lieu : nom identique d'abord, sinon
    l'un contenu dans l'autre (« Cinéma Le Dauphin » / « Le Dauphin »), le plus
    proche de l'estimation de l'agent. Un nom trop court (« Port ») ou fait seulement
    de mots génériques (« Point de vue ») ne suffit pas.
    """
    key = name_key(place)
    if is_generic(key):
        return None
    matches = []
    for poi in pois:
        poi_key = name_key(poi["name"])
        if is_generic(poi_key):
            continue
        if poi_key == key:
            rank = 0
        elif min(len(key), len(poi_key)) >= 8 and (poi_key in key or key in poi_key):
            rank = 1
        else:
            continue
        distance = haversine_distance_km(latitude, longitude, poi["latitude"], poi["longitude"])
        if distance <= LOCATE_KM:
            matches.append((rank, distance, poi))
    return min(matches, key=lambda m: m[:2])[2] if matches else None


def locate(cursor, idea: dict) -> None:
    """
    Remplace la position estimée par l'agent par celle du lieu, dans l'ordre :
      1. 'base'    : le POI de la base ETL qui porte le nom du lieu (plages, pointes,
                     monuments, cinémas...), à moins de LOCATE_KM ;
         'base_partiel' : un POI dont le nom est seulement contenu dans celui du lieu,
                     ou l'inverse. Souvent juste (« Le Dauphin » pour « Cinéma Le
                     Dauphin »), parfois un voisin (« Ménez-Hom », le sommet, pour la
                     « Chapelle Sainte-Marie du Ménez-Hom », à 2 km) : à revérifier ;
      2. 'adresse' : l'adresse postale géocodée par la Base Adresse Nationale ;
      3. 'agent'   : sinon on garde l'estimation, affichée comme approximative.
    Les positions 'base_partiel' et 'agent' sont ensuite revues par l'agent
    locate_pepites.py (relocate), qui les remplace par 'source'.
    """
    latitude, longitude = idea["latitude"], idea["longitude"]
    min_lat, min_lon, max_lat, max_lon = get_bounding_box(latitude, longitude, LOCATE_KM)
    cursor.execute("SELECT name, latitude, longitude FROM poi WHERE latitude BETWEEN %s AND %s"
                   " AND longitude BETWEEN %s AND %s", (min_lat, max_lat, min_lon, max_lon))
    pois = cursor.fetchall()
    names = [name for name in (idea.get("lieu"), idea["nom"]) if name]
    poi = next((p for p in (match_poi(name, latitude, longitude, pois) for name in names) if p), None)
    if poi:
        exact = name_key(poi["name"]) in {name_key(name) for name in names}
        idea.update(latitude=poi["latitude"], longitude=poi["longitude"],
                    position_source="base" if exact else "base_partiel")
        return
    found = geocode_address_ban(idea["adresse"], latitude, longitude) if idea.get("adresse") else None
    if found and haversine_distance_km(latitude, longitude, *found) <= RADIUS_KM:
        idea.update(latitude=found[0], longitude=found[1], position_source="adresse")
        return
    idea["position_source"] = "agent"


# Positions sûres : un POI de même nom, une adresse, une page citée par locate_pepites.
PRECISE_POSITIONS = ("base", "adresse", "source")
# Positions à faire revoir par l'agent locate_pepites.py.
TO_LOCATE_POSITIONS = ("agent", "base_partiel")


def places_to_locate(cursor, version: int, ids: list = None) -> list:
    """Les lieux à la position incertaine, pas encore essayés avec cette version des consignes."""
    sql = ("SELECT id, nom, lieu, adresse, commune, latitude, longitude FROM pepites"
           " WHERE position_source IN (%s, %s) AND (located_version IS NULL OR located_version < %s)")
    params = [*TO_LOCATE_POSITIONS, version]
    if ids is not None:
        if not ids:
            return []
        sql += f" AND id IN ({', '.join(['%s'] * len(ids))})"
        params += list(ids)
    cursor.execute(sql + " ORDER BY commune, id", params)
    return cursor.fetchall()


def relocate(cursor, places: list) -> int | None:
    """
    Fait retrouver par l'agent la position d'un lot de lieux et l'enregistre.
    Renvoie le nombre de positions retrouvées, ou None si l'agent n'a pas répondu.
    Un lieu essayé sans succès est noté (located_version) : il n'est retenté
    qu'avec une nouvelle version des consignes.
    """
    from agents.llm_service import LLMUnavailable
    from agents.locate_pepites import LOCATE_PROMPT_VERSION, locate_places
    try:
        found = locate_places(places)
    except (LLMUnavailable, json.JSONDecodeError) as error:
        logger.warning(f"[pépites] positions : recalage échoué : {error}")
        return None
    for place in places:
        if place["id"] in found:
            latitude, longitude, url = found[place["id"]]
            cursor.execute("UPDATE pepites SET latitude = %s, longitude = %s, position_source = 'source',"
                           " position_url = %s, located_version = %s, located_at = NOW() WHERE id = %s",
                           (latitude, longitude, url, LOCATE_PROMPT_VERSION, place["id"]))
        else:
            cursor.execute("UPDATE pepites SET located_version = %s, located_at = NOW() WHERE id = %s",
                           (LOCATE_PROMPT_VERSION, place["id"]))
    return len(found)


def relocate_zone(cursor, zone: dict) -> None:
    """Recale les lieux à la position incertaine d'une zone (après sa recherche des lieux)."""
    from agents.locate_pepites import BATCH_SIZE, LOCATE_PROMPT_VERSION
    places = places_to_locate(cursor, LOCATE_PROMPT_VERSION, [c["id"] for c in find_candidates(cursor, zone)])
    for start in range(0, len(places), BATCH_SIZE):
        if relocate(cursor, places[start:start + BATCH_SIZE]) is None:
            return


def relocate_missing(limit: int = None) -> None:
    """
    Rattrapage des positions : tous les lieux à la position incertaine, par lots.
    Interruptible et rejouable ; s'arrête après MAX_CONSECUTIVE_FAILURES échecs
    d'affilée (quota). `limit` borne le nombre de lots (pour un pilote).
    """
    from agents.locate_pepites import BATCH_SIZE, LOCATE_PROMPT_VERSION
    connection = MySQLUtils.connect()
    cursor = connection.cursor(dictionary=True)
    try:
        places = places_to_locate(cursor, LOCATE_PROMPT_VERSION)
        batches = [places[i:i + BATCH_SIZE] for i in range(0, len(places), BATCH_SIZE)][:limit]
        logger.info(f"[pépites] positions : {len(places)} lieu(x) à recaler, {len(batches)} lot(s)")
        done = in_a_row = 0
        for number, batch in enumerate(batches, start=1):
            found = relocate(cursor, batch)
            connection.commit()
            if found is None:
                in_a_row += 1
                if in_a_row >= MAX_CONSECUTIVE_FAILURES:
                    logger.warning("[pépites] positions : rattrapage arrêté, l'agent ne répond plus (quota épuisé ?)")
                    break
                continue
            done, in_a_row = done + found, 0
            logger.info(f"[pépites] positions lot {number}/{len(batches)} : {found}/{len(batch)} retrouvée(s),"
                        f" {done} au total")
    finally:
        cursor.close()
        MySQLUtils.disconnect(connection)


# Une idée déjà connue revient sous le même nom, à la ponctuation près, mais pas toujours
# au même endroit : la position estimée par l'agent varie de quelques kilomètres d'une
# recherche à l'autre (« Vallée du Queffleuth » trouvée deux fois, à 2,2 km d'écart).
# Un nom précis suffit à la reconnaître dans ce rayon ; un nom générique (« Lavoir »)
# peut désigner un autre lieu tout proche, on garde alors 300 m.
SAME_PLACE_KM = 3
SAME_GENERIC_PLACE_KM = 0.3


def same_place(idea: dict, existing: list) -> dict | None:
    """L'idée déjà en base qui désigne le même lieu que `idea`, ou None."""
    key = name_key(idea["nom"])
    max_km = SAME_GENERIC_PLACE_KM if is_generic(key) else SAME_PLACE_KM
    return next((c for c in existing if name_key(c["nom"]) == key
                 and haversine_distance_km(c["latitude"], c["longitude"], idea["latitude"], idea["longitude"]) < max_km),
                None)


def save_pepite(cursor, idea: dict, existing: list, prompt_version: int, model: str) -> None:
    """
    Enregistre une idée trouvée par l'agent. Si elle est déjà en base (same_place),
    on la met à jour : c'est ainsi qu'une idée ancienne est revérifiée (verified_at
    repart de maintenant).
    """
    same = same_place(idea, existing)
    if same and same.get("position_source") in PRECISE_POSITIONS and idea.get("position_source") not in PRECISE_POSITIONS:
        # Retrouvée un an plus tard, l'idée revient avec une estimation : on garde la
        # position déjà recalée.
        idea.update(latitude=same["latitude"], longitude=same["longitude"], position_source=same["position_source"])
    values = (
        idea["nom"], idea["categorie"], idea["description"], idea.get("commune"),
        json.dumps(idea.get("themes") or []), idea.get("lieu"),
        idea.get("adresse"), idea["latitude"], idea["longitude"], idea.get("position_source"),
        idea.get("date_debut"), idea.get("date_fin"),
        json.dumps(idea.get("jours_semaine") or []), idea.get("horaires"), idea.get("heure_debut"), idea.get("tarif"),
        idea["creneau"],
        idea.get("duree_h"), idea["exterieur"], idea["permanent"], idea["note"],
        json.dumps(idea.get("sources") or [], ensure_ascii=False), prompt_version, model,
    )
    if same:
        cursor.execute("""
            UPDATE pepites SET nom = %s, categorie = %s, description = %s, commune = %s, themes = %s, lieu = %s,
                adresse = %s, latitude = %s, longitude = %s, position_source = %s,
                position_url = IF(position_source = 'source', position_url, NULL), date_debut = %s, date_fin = %s, jours_semaine = %s,
                horaires = %s, heure_debut = %s, tarif = %s, creneau = %s, duree_h = %s, exterieur = %s, permanent = %s, note = %s,
                sources = %s, prompt_version = %s, model = %s, verified_at = NOW()
            WHERE id = %s
        """, (*values, same["id"]))
    else:
        cursor.execute("""
            INSERT INTO pepites (nom, categorie, description, commune, themes, lieu, adresse, latitude, longitude,
                position_source, date_debut, date_fin, jours_semaine, horaires, heure_debut, tarif, creneau,
                duree_h, exterieur, permanent, note, sources, prompt_version, model, found_at, verified_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, NOW(), NOW())
        """, values)


# Heure indicative de chaque moment de la journée, pour ranger les pépites d'un jour.
MOMENT_HOURS = {"matin": 10, "midi": 12.5, "apres_midi": 15, "coucher_soleil": 18, "soiree": 21}


def day_order(pepite: dict) -> float:
    """
    Heure indicative d'une pépite dans la journée : le moment choisi par Vany, sinon
    son heure de début, sinon son créneau (une idée choisie avant que Vany ne donne
    le moment, ou classée par le code seul).
    """
    if pepite.get("moment") in MOMENT_HOURS:
        return MOMENT_HOURS[pepite["moment"]]
    if pepite.get("heure_debut") is not None:
        return pepite["heure_debut"]
    return MOMENT_HOURS["soiree"] if pepite.get("creneau") == "soiree" else MOMENT_HOURS["apres_midi"]


def fetch_chosen_pepites(cursor, trip_day_id: int) -> list:
    """Les idées ajoutées à un jour, dans l'ordre de la journée (tableau récap, carte, PDF)."""
    return sorted((c for c in day_links(cursor, trip_day_id) if c["statut"] == "choisie"), key=day_order)


def trail_tips(pepites: list, trace: list) -> list:
    """Les lieux et points de vue sur le parcours, dans l'ordre de la marche (4 au plus)."""
    on_trail = []
    for pepite in pepites:
        rank = trace_position(pepite, trace) if pepite["categorie"] in TRAIL_CATEGORIES else None
        if rank is not None and (pepite.get("note") or 0) >= NOTE_MIN:
            on_trail.append((rank, pepite))
    on_trail.sort(key=lambda item: item[0])
    return [pepite for _, pepite in on_trail[:MAX_TRAIL_TIPS]]


def fetch_trail_tips(cursor, hike_mongo_id: str | None) -> list:
    """
    Conseils « En chemin » d'un jour de rando (tableau récap, carte, PDF). Aucun appel
    à l'agent : on réutilise les idées déjà en base autour du tracé.
    """
    trace = hike_trace(hike_mongo_id) if hike_mongo_id else []
    if not trace:
        return []
    south, west, _, _ = get_bounding_box(min(p[0] for p in trace), min(p[1] for p in trace), TRAIL_KM)
    _, _, north, east = get_bounding_box(max(p[0] for p in trace), max(p[1] for p in trace), TRAIL_KM)
    cursor.execute("SELECT * FROM pepites WHERE latitude BETWEEN %s AND %s AND longitude BETWEEN %s AND %s",
                   (south, north, west, east))
    return trail_tips([_read_pepite_row(row) for row in cursor.fetchall()], trace)


def trail_tips_for_hikes(hike_ids: list) -> dict:
    """
    Recommandations « En chemin » de Vany pour des randos, dès leur choix (étape 2) :
    {id de la rando: [lieux dans l'ordre de la marche]}. Une rando sans lieu repéré
    n'apparaît pas.
    """
    if not hike_ids:
        return {}
    connection = MySQLUtils.connect()
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute(f"SELECT id, mongo_id FROM hikes WHERE id IN ({', '.join(['%s'] * len(hike_ids))})",
                       list(hike_ids))
        tips = {}
        for hike in cursor.fetchall():
            found = fetch_trail_tips(cursor, hike["mongo_id"])
            if found:
                tips[hike["id"]] = [trail_tip_display(tip) for tip in found]
        return tips
    finally:
        cursor.close()
        MySQLUtils.disconnect(connection)


# =============================================================================
# 5. CHERCHER (AGENT) ET PRÉPARER LES IDÉES D'UN JOUR
# =============================================================================

def search_and_store(cursor, day: dict, mode: str, trip_day_id: int = None) -> int | None:
    """
    Lance une recherche de l'agent ("lieux" ou "agenda") pour la zone et enregistre
    ce qu'il trouve. Renvoie le nombre d'idées, ou None si l'agent n'a pas répondu
    (quota épuisé, délai dépassé...) : rien n'est alors enregistré, la recherche
    sera retentée à la prochaine occasion.
    """
    # Import ici et non en haut du fichier : les agents importent eux-mêmes ce module.
    from agents.discover_places import search_places
    from agents.find_pepites import search_agenda
    from agents.llm_service import LLMUnavailable

    # L'agent ne cherche pas ce qu'on connaît déjà et qui est à jour ; une
    # idée trop ancienne peut être retrouvée, elle est alors mise à jour.
    in_zone = find_candidates(cursor, day)
    known_names = [c["nom"] for c in in_zone if is_fresh(c, datetime.now())]
    try:
        search = search_places if mode == "lieux" else search_agenda
        ideas, model, version = search(day, known_names)
    except (LLMUnavailable, json.JSONDecodeError) as error:
        logger.warning(f"[pépites] {mode} {day.get('spot_name') or day.get('city_name')} : recherche échouée : {error}")
        return None
    for idea in ideas:
        locate(cursor, idea)
        save_pepite(cursor, idea, in_zone, version, model)
    record_search(cursor, day, mode, len(ideas), version, trip_day_id)
    return len(ideas)


def search_zone(plan_id: int, day_number: int) -> None:
    """
    Recherches autour de la ville du jour, lancées dès qu'elle est choisie (étape 1) :
    l'agenda aux dates du séjour, et les lieux si l'ETL ne les a pas encore cherchés.
    """
    connection = MySQLUtils.connect()
    cursor = connection.cursor(dictionary=True)
    try:
        day = load_day_context(cursor, plan_id, day_number)
        if day is None:
            return
        for mode in missing_searches(cursor, day):
            search_and_store(cursor, day, mode)
            connection.commit()
    finally:
        cursor.close()
        MySQLUtils.disconnect(connection)


def _city_context(cursor, city: dict) -> dict:
    """Une ville vue comme une zone de recherche des lieux : son centre et ses randos."""
    cursor.execute("SELECT name FROM hikes WHERE city_id = %s ORDER BY name", (city["id"],))
    return {"city_name": city["name"], "has_spot": False, "points": [(city["latitude"], city["longitude"])],
            "trip_hikes": [row["name"] for row in cursor.fetchall()]}


def _search_places(cursor, city: dict) -> str:
    """
    Cherche les lieux d'une ville, sauf si une recherche récente couvre déjà sa zone.
    Renvoie "couverte" (rien à faire), "faite" ou "echec" (l'agent n'a pas répondu).
    """
    if _places_covered(cursor, city):
        return "couverte"
    zone = _city_context(cursor, city)
    if search_and_store(cursor, zone, "lieux") is None:
        return "echec"
    # Puis la position exacte des lieux trouvés que le code n'a pas su recaler.
    # Un échec ici n'empêche pas la ville d'être faite : relocate_missing reprendra.
    relocate_zone(cursor, zone)
    return "faite"


def _places_covered(cursor, city: dict) -> bool:
    """Une recherche récente des lieux couvre-t-elle déjà la zone de la ville ?"""
    return recent_search_exists(cursor, _city_context(cursor, city), "lieux", prompt_version("lieux"))


def search_city_places(city_name: str) -> None:
    """
    Lieux incontournables autour d'une ville, cherchés une fois pour toutes. Appelé
    par l'ETL après le chargement des POI de la ville (etl_pipeline.py) : la position
    des lieux trouvés est recalée sur ces POI (locate).
    """
    connection = MySQLUtils.connect()
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id, name, latitude, longitude FROM cities WHERE name = %s LIMIT 1", (city_name,))
        city = cursor.fetchone()
        if city is None:
            logger.warning(f"[pépites] lieux : ville inconnue « {city_name} »")
            return
        _search_places(cursor, city)
        connection.commit()
    finally:
        cursor.close()
        MySQLUtils.disconnect(connection)


# Après autant d'échecs d'affilée, l'agent ne répond plus (quota de l'abonnement
# épuisé le plus souvent) : le rattrapage s'arrête au lieu d'échouer ville après ville.
MAX_CONSECUTIVE_FAILURES = 3


def run_catch_up(cities: list, search_city, limit: int = None) -> dict:
    """
    Boucle du rattrapage : `search_city(city)` renvoie "couverte", "faite" ou "echec".
    S'arrête après `limit` recherches lancées, ou après MAX_CONSECUTIVE_FAILURES échecs
    d'affilée. Renvoie le bilan {"faites", "echecs", "arret"}.
    Le compteur « ville N/total » suit la liste reçue ; une ville peut y être passée
    parce qu'une voisine cherchée entre-temps couvre déjà sa zone : il en reste donc
    « au plus » total - N.
    """
    done = failed = in_a_row = 0
    total = len(cities)
    for position, city in enumerate(cities, start=1):
        if limit is not None and done + failed >= limit:
            break
        status = search_city(city)
        if status == "couverte":
            continue
        logger.info(f"[pépites] rattrapage ville {position}/{total} : {city['name']}"
                    f" {'faite' if status == 'faite' else 'en échec'}, reste au plus {total - position} ville(s)")
        if status == "faite":
            done, in_a_row = done + 1, 0
            continue
        failed, in_a_row = failed + 1, in_a_row + 1
        if in_a_row >= MAX_CONSECUTIVE_FAILURES:
            logger.warning(f"[pépites] rattrapage arrêté à {city['name']} : {in_a_row} échecs d'affilée,"
                           " l'agent ne répond plus (quota épuisé ?). Relancer plus tard : il reprendra"
                           " aux villes qui n'ont pas encore de lieux.")
            return {"faites": done, "echecs": failed, "arret": True}
    return {"faites": done, "echecs": failed, "arret": False}


def search_missing_places(limit: int = None) -> None:
    """
    Rattrapage : cherche les lieux de toutes les villes déjà en base qui n'en ont pas
    encore (2 à 3 min par ville). Interruptible et rejouable : une ville dont la zone
    est déjà couverte, par elle-même ou par une voisine à moins de 5 km, est passée ;
    une ville en échec n'est pas notée et sera retentée. `limit` borne le nombre de
    recherches (pour un pilote).
    """
    connection = MySQLUtils.connect()
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id, name, latitude, longitude FROM cities ORDER BY id")
        cities = cursor.fetchall()
        # Seules les villes encore sans lieux sont comptées : le compteur dit ce qui reste.
        todo = [city for city in cities if not _places_covered(cursor, city)]
        logger.info(f"[pépites] rattrapage : {len(todo)} ville(s) sans lieux sur {len(cities)}")

        def search_city(city):
            status = _search_places(cursor, city)
            connection.commit()
            return status

        report = run_catch_up(todo, search_city, limit)
        left = sum(1 for city in todo if not _places_covered(cursor, city))
        logger.info(f"[pépites] rattrapage {'interrompu' if report['arret'] or left else 'terminé'} :"
                    f" {report['faites']} recherche(s) faite(s), {report['echecs']} échec(s),"
                    f" {left} ville(s) encore sans lieux")
    finally:
        cursor.close()
        MySQLUtils.disconnect(connection)


def _top_up(cursor, day: dict, proposed: set, section: str) -> int:
    """
    Complète une section des propositions du jour (`proposed`, mis à jour) jusqu'à
    MAX_IDEAS. Le code retient les idées possibles ce jour-là, les plus proches
    (POOL_SIZE) ; Vany y choisit les meilleures pour cette journée, avec une phrase pour
    chacune et son coup de cœur (agents/choose_pepites.py). S'il ne répond pas, le code
    prend les plus proches. Renvoie le nombre de places restant dans la section.
    """
    from agents.choose_pepites import choose_pepites

    links = day_links(cursor, day["trip_day_id"])
    in_section = [c for c in links if c["id"] in proposed and pepite_section(c) == section]
    slots = MAX_IDEAS[section] - len(in_section)
    if slots <= 0:
        return 0
    excluded = {c["id"] for c in links} | ids_used_elsewhere(cursor, day)
    program = program_elsewhere(cursor, day)
    ideas = [evaluate(c, day) for c in find_candidates(cursor, day)
             if c["id"] not in excluded and pepite_section(c) == section and not same_site_as(c, program)]
    pool = sorted((i for i in ideas if i), key=lambda i: i["closeness"])[:POOL_SIZE]
    if not pool:
        return slots

    already = [c["nom"] for c in links if c["id"] in proposed]
    choice = choose_pepites(day, pool, slots, already, program)
    if choice is None:
        choice = {"ids": [i["id"] for i in pool[:slots]], "why": {}, "moment": {}, "favorite": None}
    # Un coup de cœur par section : celui d'un choix précédent est gardé.
    if any(c["coup_de_coeur"] for c in in_section):
        choice["favorite"] = None
    for pepite_id in choice["ids"]:
        cursor.execute("INSERT INTO trip_day_pepites (trip_day_id, pepite_id, pourquoi, moment, coup_de_coeur)"
                       " VALUES (%s, %s, %s, %s, %s)",
                       (day["trip_day_id"], pepite_id, choice["why"].get(pepite_id),
                        choice["moment"].get(pepite_id), pepite_id == choice["favorite"]))
        proposed.add(pepite_id)
    return slots - len(choice["ids"])


def _still_proposed(cursor, day: dict) -> set:
    """Les idées proposées ou ajoutées à ce jour, toujours compatibles avec lui."""
    return {link["id"] for link in day_links(cursor, day["trip_day_id"])
            if link["statut"] in ("proposee", "choisie") and evaluate(link, day) is not None}


def prepare_day(plan_id: int, day_number: int) -> None:
    """
    Premier temps, appelé à chaque choix de spot, en quelques secondes : l'étape 5
    n'attend pas l'agenda pour proposer ce qui est déjà en base.
      1. retire les idées devenues incompatibles (le jour a pu être modifié) ;
         une idée CHOISIE passe en 'retiree' pour prévenir l'utilisateur ;
      2. complète chaque section avec les idées en base ;
      3. lance le second temps en tâche de fond (complete_day).
    """
    connection = MySQLUtils.connect()
    cursor = connection.cursor(dictionary=True)
    try:
        day = load_day_context(cursor, plan_id, day_number)
        if day is None or not day["has_spot"]:
            return

        still_proposed = _still_proposed(cursor, day)
        for link in day_links(cursor, day["trip_day_id"]):
            if link["id"] in still_proposed or link["statut"] == "retiree":
                continue
            if link["statut"] == "choisie":
                cursor.execute("UPDATE trip_day_pepites SET statut = 'retiree' WHERE trip_day_id = %s AND pepite_id = %s",
                               (day["trip_day_id"], link["id"]))
            else:
                cursor.execute("DELETE FROM trip_day_pepites WHERE trip_day_id = %s AND pepite_id = %s",
                               (day["trip_day_id"], link["id"]))
        connection.commit()

        for section in MAX_IDEAS:
            _top_up(cursor, day, still_proposed, section)
            connection.commit()
    finally:
        cursor.close()
        MySQLUtils.disconnect(connection)
    start_completion(plan_id, day_number)


def searches_to_run(missing: list, free: dict) -> list:
    """Parmi les recherches qui manquent, celles qui peuvent encore remplir une section."""
    section_of_search = {"lieux": "saison", "agenda": "sejour"}
    return [mode for mode in missing if free[section_of_search[mode]] > 0]


def complete_day(plan_id: int, day_number: int) -> None:
    """
    Second temps, en tâche de fond : le voyageur peut continuer sans attendre.
    Attend la recherche lancée au choix de la ville (_search_lock), puis, s'il reste de
    la place dans une section :
      - lance les recherches qui manquent dans la zone du spot (agenda, lieux) ;
      - ou, si le séjour a déjà pris les lieux de la zone (long séjour au même endroit) :
        recherche complémentaire de lieux, une seule fois pour ce jour ;
    et propose ce que ces recherches ont trouvé (le rappel de la barre du bas, day_news).
    """
    connection = MySQLUtils.connect()
    cursor = connection.cursor(dictionary=True)
    try:
        day = load_day_context(cursor, plan_id, day_number)
        if day is None or not day["has_spot"]:
            return
        with _choice_lock(plan_id):
            still_proposed = _still_proposed(cursor, day)
            free = {section: _top_up(cursor, day, still_proposed, section) for section in MAX_IDEAS}
            connection.commit()

        missing = missing_searches(cursor, day)
        for mode in searches_to_run(missing, free):
            search_and_store(cursor, day, mode)
            connection.commit()
        if free["saison"] > 0 and "lieux" not in missing:
            in_zone = {c["id"] for c in find_candidates(cursor, day)}
            if in_zone & ids_used_elsewhere(cursor, day) and not complementary_search_done(cursor, day["trip_day_id"]):
                search_and_store(cursor, day, "lieux", trip_day_id=day["trip_day_id"])
                connection.commit()

        # Le spot a pu changer pendant la recherche : on repart de l'état du jour.
        day = load_day_context(cursor, plan_id, day_number)
        if day and day["has_spot"]:
            with _choice_lock(plan_id):
                still_proposed = _still_proposed(cursor, day)
                for section in MAX_IDEAS:
                    _top_up(cursor, day, still_proposed, section)
                connection.commit()
    finally:
        cursor.close()
        MySQLUtils.disconnect(connection)


# Tâches en cours, pour répondre "recherche" à la page récap pendant ce temps.
# Même principe que le rafraîchissement météo de api/routers/step1.py.
_searching = set()   # (plan_id, day_number) : recherches lancées au choix de la ville
_preparing = set()   # (plan_id, day_number) : préparations lancées au choix du spot
_completing = set()  # (plan_id, day_number) : second temps, recherches et idées qu'elles apportent
_running_lock = threading.Lock()
# Deux verrous par séjour. Les recherches passent l'une après l'autre, pour ne pas
# chercher deux fois la même chose ; la préparation d'un jour ne les attend pas. Les choix
# de Vany aussi passent l'un après l'autre : deux choix simultanés proposeraient la même idée.
_search_locks = {}
_choice_locks = {}


def _search_lock(plan_id: int) -> threading.Lock:
    with _running_lock:
        return _search_locks.setdefault(plan_id, threading.Lock())


def _choice_lock(plan_id: int) -> threading.Lock:
    with _running_lock:
        return _choice_locks.setdefault(plan_id, threading.Lock())


def _start_in_background(task, running: set, lock_of_plan, plan_id: int, day_number: int) -> None:
    """Lance task(plan_id, day_number) en tâche de fond, sauf si elle tourne déjà."""
    key = (plan_id, day_number)
    with _running_lock:
        if key in running:
            return
        running.add(key)

    def run():
        try:
            with lock_of_plan(plan_id):
                task(plan_id, day_number)
        except Exception as error:   # une tâche de fond ne doit jamais planter l'API
            logger.error(f"[pépites] plan {plan_id} jour {day_number} : {task.__name__} a échoué : {error}")
        finally:
            with _running_lock:
                running.discard(key)

    threading.Thread(target=run, daemon=True).start()


def start_zone_search(plan_id: int, day_number: int) -> None:
    """Ville choisie (étape 1) : recherche autour de la ville, en tâche de fond."""
    _start_in_background(search_zone, _searching, _search_lock, plan_id, day_number)


def start_preparation(plan_id: int, day_number: int) -> None:
    """Spot choisi (étape 3) : préparation des idées du jour, en tâche de fond."""
    _start_in_background(prepare_day, _preparing, _choice_lock, plan_id, day_number)


def start_completion(plan_id: int, day_number: int) -> None:
    """Second temps de la préparation : recherches manquantes, après celle de la ville."""
    _start_in_background(complete_day, _completing, _search_lock, plan_id, day_number)


# =============================================================================
# 6. CE QUE L'API RENVOIE ET LES CHOIX DE L'UTILISATEUR
# =============================================================================

def get_day_state(plan_id: int, day_number: int) -> dict:
    """
    Contenu de l'étape « Les pépites de Vany » pour un jour :
      - 'recherche'    : la préparation tourne encore, ou aucune idée n'est prête ;
      - 'propositions' : les idées (champ "ideas", chacune avec sa "section" et "added"
                         si elle est ajoutée à la journée), éventuellement "removed", le
                         nom d'une idée ajoutée qui ne tient plus, et "agenda_pending"
                         tant que les recherches peuvent encore apporter des idées ;
      - 'rien'         : Vany a cherché pour ce jour mais n'a rien trouvé ;
      - 'vide'         : pas de recherche pour ce jour (spot pas choisi, ancien plan).
    Dès que le spot est choisi, "trail_tips" donne les lieux à voir en chemin sur la
    rando du jour et "spot" la position du spot : la page cadre sa carte dessus
    sans attendre la fin de la recherche.
    """
    with _running_lock:
        key = (plan_id, day_number)
        preparing = key in _preparing
        pending = key in _searching or key in _completing

    connection = MySQLUtils.connect()
    cursor = connection.cursor(dictionary=True)
    try:
        day = load_day_context(cursor, plan_id, day_number)
        if day is None or not day["has_spot"]:
            return {"state": "recherche" if preparing or pending else "vide"}
        links = day_links(cursor, day["trip_day_id"])
        searched = any(recent_search_exists(cursor, day, mode) for mode in SEARCH_FRESH_DAYS)
        trail_tips = fetch_trail_tips(cursor, day["hike_mongo_id"])
    finally:
        cursor.close()
        MySQLUtils.disconnect(connection)

    context = {
        "trail_tips": [trail_tip_display(tip) for tip in trail_tips],
        "spot": {"name": day["spot_name"], "latitude": day["spot_latitude"], "longitude": day["spot_longitude"]},
    }
    if preparing:
        return {"state": "recherche"} | context
    removed = next((c["nom"] for c in links if c["statut"] == "retiree"), None)
    # evaluate() garde le statut de la ligne ; une idée devenue incompatible depuis
    # la préparation (ex : la date d'une expo est passée) n'est plus montrée.
    ideas = [i for i in (evaluate(c, day) for c in links if c["statut"] in ("proposee", "choisie")) if i]
    if not ideas and pending:
        return {"state": "recherche"} | context
    if not ideas and not removed:
        state = pepite_nothing_texts(day["day_date"]) | {"state": "rien"} if searched else {"state": "vide"}
        return state | context
    texts = pepite_day_texts(day["day_date"], day["hike_duration_h"], free_time_h(day["hike_duration_h"]))
    return texts | context | {"state": "propositions", "removed": removed, "agenda_pending": pending,
                              "ideas": [pepite_display(i, top=top) for i, top in arrange_ideas(ideas)]}


def arrange_ideas(ideas: list) -> list:
    """
    Ordre d'affichage : les intemporels, puis les idées du séjour ; dans chaque section,
    le coup de cœur en tête, puis les plus proches. Renvoie [(idée, coup de cœur ?)].
    Un coup de cœur par section, désigné par Vany. Si Vany n'a pas répondu, la mieux notée
    des intemporels prend le badge ; une idée du séjour ne l'a que s'il l'a désignée.
    """
    arranged = []
    for section in MAX_IDEAS:
        in_section = [i for i in ideas if pepite_section(i) == section]
        favorite = next((i for i in in_section if i.get("coup_de_coeur")), None)
        if favorite is None and section == "saison":
            favorite = max(in_section, key=lambda i: i.get("note") or 0, default=None)
        arranged += [(i, i is favorite) for i in sorted(in_section, key=lambda i: (i is not favorite, i["closeness"]))]
    return arranged


def day_news(plan_id: int) -> list:
    """
    Les idées du séjour arrivées depuis la dernière visite de l'étape 5, jour par jour,
    pour le rappel de la barre du bas : le voyageur a pu continuer sans attendre l'agenda.
    """
    connection = MySQLUtils.connect()
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT td.day_number, td.city_id, td.hike_id, td.spot_id, tp.start_date,
                   COUNT(*) AS nb, MAX(tdp.coup_de_coeur) AS favorite
            FROM trip_day_pepites tdp
            JOIN trip_days td ON td.id = tdp.trip_day_id
            JOIN trip_plans tp ON tp.id = td.trip_plan_id
            JOIN pepites p ON p.id = tdp.pepite_id
            WHERE td.trip_plan_id = %s AND tdp.vue = 0 AND p.permanent = 0 AND tdp.statut = 'proposee'
            GROUP BY td.id ORDER BY td.day_number
        """, (plan_id,))
        return [{"day_number": row["day_number"], "city_id": row["city_id"], "hike_id": row["hike_id"],
                 "spot_id": row["spot_id"],
                 "text": pepite_news_text(row["nb"], row["start_date"] + timedelta(days=row["day_number"] - 1),
                                          row["favorite"])}
                for row in cursor.fetchall()]
    finally:
        cursor.close()
        MySQLUtils.disconnect(connection)


def mark_seen(plan_id: int, day_number: int) -> None:
    """Le voyageur a vu les idées de ce jour à l'étape 5 : le rappel n'a plus lieu d'être."""
    connection = MySQLUtils.connect()
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute("""
            UPDATE trip_day_pepites tdp JOIN trip_days td ON td.id = tdp.trip_day_id
            SET tdp.vue = 1 WHERE td.trip_plan_id = %s AND td.day_number = %s
        """, (plan_id, day_number))
        connection.commit()
    finally:
        cursor.close()
        MySQLUtils.disconnect(connection)


def _trip_day_id(cursor, plan_id: int, day_number: int) -> int | None:
    cursor.execute("SELECT id FROM trip_days WHERE trip_plan_id = %s AND day_number = %s", (plan_id, day_number))
    row = cursor.fetchone()
    return row["id"] if row else None


def set_added(plan_id: int, day_number: int, pepite_id: int, added: bool) -> None:
    """Ajoute une idée à la journée (added=True) ou l'en retire ; plusieurs idées peuvent être ajoutées."""
    connection = MySQLUtils.connect()
    cursor = connection.cursor(dictionary=True)
    try:
        trip_day_id = _trip_day_id(cursor, plan_id, day_number)
        if trip_day_id is None:
            return
        cursor.execute("UPDATE trip_day_pepites SET statut = %s WHERE trip_day_id = %s AND pepite_id = %s",
                       ("choisie" if added else "proposee", trip_day_id, pepite_id))
        if added:
            # L'utilisateur a fait un nouveau choix : l'ancienne idée "retiree" n'a plus à être signalée.
            cursor.execute("DELETE FROM trip_day_pepites WHERE trip_day_id = %s AND statut = 'retiree'", (trip_day_id,))
        connection.commit()
    finally:
        cursor.close()
        MySQLUtils.disconnect(connection)
