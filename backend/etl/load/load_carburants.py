"""
Chargement des stations-service de l'État : poi, stations_carburant et prix_carburants. Les tables sont créées dans
db_init/db_randovango.py.

Une station est un poi de la source « prix-carburants » (original_id = identifiant de l'État), lié au service « fuel » :
l'étape 4 la range donc dans l'onglet gasoil sans rien changer. Son nom et sa position sont remis à jour à chaque
passage, depuis OSM, sauf ce qu'un humain a corrigé dans /supervision (table decisions, non annulée) : ce champ-là n'est
plus jamais réécrit ici. Cas du 11 novembre 2026 : le Carrefour Contact de Plouguerneau, renommé à la main, serait
redevenu « Station-service » au rafraîchissement suivant des prix.

Les prix d'une station sont remplacés en bloc : la table garde exactement ce que dit le dernier fichier.

Les signaux d'une station douteuse (transform_carburants) vont dans poi_signals, sous deux sources : SIGNALS_FROM_OSM
pour le passage par ville, SIGNALS_FROM_STATE pour le rafraîchissement des prix. Chaque passage remplace les siens :
un signal qui n'a plus lieu d'être est effacé s'il est encore à relire, jamais s'il a été relu. Une station retirée ou
fusionnée à la main ne reçoit plus de signal. Le masquage, lui, est fait par services/poi_triage_service.py.
"""
import json

from etl.load.load_poi import get_or_create_source, insert_histo_poi, insert_service_and_link
from etl.load.load_poi_checks import save_signal
from utils.db_utils import MySQLUtils
from utils.logger_util import LoggerUtil

logger = LoggerUtil.get_logger("etl_carburants")

SOURCE_NAME = "prix-carburants"
FUEL_SERVICE = "fuel"
STATION_COLUMNS = ("pdv_id", "osm_element", "lien_osm", "marque", "adresse_etat", "code_postal", "ville_etat",
                   "latitude_etat", "longitude_etat", "route", "automate_24_24", "horaires", "services",
                   "fermeture_type", "fermeture_debut", "fermeture_fin", "lu_le")
JSON_COLUMNS = ("horaires", "services")
POI_COLUMNS = ("name", "latitude", "longitude", "address")
SIGNALS_FROM_OSM = "carburants_osm"
SIGNALS_FROM_STATE = "carburants_etat"
REMOVING_DECISIONS = ("retirer", "fusionner")


def human_fields(cursor, source_id: int) -> dict:
    """
    {poi_id: colonnes de poi corrigées par une décision non annulée} pour les stations de l'État. Une décision garde
    les valeurs d'avant dans detail.avant (services_review) : ce sont les colonnes qu'elle a changées.
    """
    cursor.execute(
        """
        SELECT d.objet_id, d.detail FROM decisions d JOIN poi p ON p.id = d.objet_id
        WHERE d.objet_type = 'poi' AND d.annulee_at IS NULL AND p.source_id = %s
        """,
        (source_id,))
    fields = {}
    for poi_id, detail in cursor.fetchall():
        try:
            before = (json.loads(detail) if isinstance(detail, (str, bytes)) else detail or {}).get("avant") or {}
        except (ValueError, AttributeError):
            continue
        fields.setdefault(poi_id, set()).update(column for column in before if column in POI_COLUMNS)
    return fields


def _upsert_poi(cursor, source_id: int, pdv_id: str, poi: dict, protected: dict) -> int:
    """Crée le poi d'une station, ou remet à jour ses colonnes, sauf celles qu'un humain a corrigées (protected)."""
    cursor.execute("SELECT id FROM poi WHERE original_id = %s AND source_id = %s", (pdv_id, source_id))
    found = cursor.fetchone()
    if found is None:
        cursor.execute(
            """
            INSERT INTO poi (original_id, name, latitude, longitude, address, source_id, verifie)
            VALUES (%s, %s, %s, %s, %s, %s, 1)
            """,
            (pdv_id, poi["name"], poi["latitude"], poi["longitude"], poi["address"], source_id))
        return cursor.lastrowid
    poi_id = found[0]
    columns = [column for column in POI_COLUMNS if column not in protected.get(poi_id, set())]
    if columns:
        cursor.execute(f"UPDATE poi SET {', '.join(f'{c} = %s' for c in columns)} WHERE id = %s",
                       (*(poi[c] for c in columns), poi_id))
    return poi_id


def removed_by_hand(cursor, source_id: int) -> set:
    """Les stations qu'un humain a retirées ou fusionnées (décision non annulée) : elles ne sont plus signalées."""
    marks = ", ".join(["%s"] * len(REMOVING_DECISIONS))
    cursor.execute(
        f"""
        SELECT DISTINCT d.objet_id FROM decisions d JOIN poi p ON p.id = d.objet_id
        WHERE d.objet_type = 'poi' AND d.annulee_at IS NULL AND d.decision IN ({marks}) AND p.source_id = %s
        """,
        (*REMOVING_DECISIONS, source_id))
    return {row[0] for row in cursor.fetchall()}


def _replace_signals(cursor, poi_id: int, source: str, signals: list, removed: set) -> None:
    """Les signaux de ce passage sur une station ; ceux d'avant qui ne sont plus vrais, encore à relire, sont effacés."""
    kinds = [kind for kind, _ in signals] if poi_id not in removed else []
    for kind, detail in signals if poi_id not in removed else []:
        save_signal(cursor, poi_id, source, kind, detail)
    stale = "" if not kinds else f" AND signal_type NOT IN ({', '.join(['%s'] * len(kinds))})"
    cursor.execute(f"DELETE FROM poi_signals WHERE poi_id = %s AND source = %s AND statut = 'a_relire'{stale}",
                   (poi_id, source, *kinds))


def _upsert_station(cursor, poi_id: int, station: dict) -> None:
    values = [json.dumps(station[c], ensure_ascii=False) if c in JSON_COLUMNS and station[c] is not None
              else station[c] for c in STATION_COLUMNS]
    columns = ", ".join(STATION_COLUMNS)
    updates = ", ".join(f"{c} = VALUES({c})" for c in STATION_COLUMNS if c != "pdv_id")
    cursor.execute(
        f"INSERT INTO stations_carburant (poi_id, {columns}) VALUES (%s, {', '.join(['%s'] * len(STATION_COLUMNS))}) "
        f"ON DUPLICATE KEY UPDATE {updates}",
        (poi_id, *values))


def _replace_prices(cursor, poi_id: int, prices: list) -> None:
    cursor.execute("DELETE FROM prix_carburants WHERE poi_id = %s", (poi_id,))
    for price in prices:
        cursor.execute(
            """
            INSERT INTO prix_carburants (poi_id, carburant, prix, releve_le, rupture_type, rupture_debut, rupture_fin)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (poi_id, price["carburant"], price["prix"], price["releve_le"], price["rupture_type"],
             price["rupture_debut"], price["rupture_fin"]))


def load_stations(rows: list, city_name: str | None) -> int:
    """Charge les stations d'une ville (ou du rafraîchissement des prix si city_name est None). Une seule transaction."""
    if not rows:
        return 0
    cnx = MySQLUtils.connect()
    cursor = cnx.cursor()
    try:
        source_id = get_or_create_source(cursor, SOURCE_NAME)
        protected = human_fields(cursor, source_id)
        removed = removed_by_hand(cursor, source_id)
        signals_source = SIGNALS_FROM_OSM if city_name else SIGNALS_FROM_STATE
        for row in rows:
            poi_id = _upsert_poi(cursor, source_id, row["station"]["pdv_id"], row["poi"], protected)
            insert_service_and_link(cursor, poi_id, FUEL_SERVICE)
            if city_name:
                insert_histo_poi(cursor, poi_id, city_name)
            _upsert_station(cursor, poi_id, row["station"])
            _replace_prices(cursor, poi_id, row["prix"])
            _replace_signals(cursor, poi_id, signals_source, row.get("signaux", []), removed)
        cnx.commit()
    except Exception:
        cnx.rollback()
        raise
    finally:
        cursor.close()
        MySQLUtils.disconnect(cnx)
    logger.info(f"[Load] : {len(rows)} stations chargées{f' pour {city_name}' if city_name else ''}")
    return len(rows)


def load_missing_signals(signals: dict, known: dict) -> None:
    """Les signaux des stations de la base absentes du fichier de l'État ({pdv_id: [(signal, détail)]})."""
    if not signals:
        return
    cnx = MySQLUtils.connect()
    cursor = cnx.cursor()
    try:
        removed = removed_by_hand(cursor, get_or_create_source(cursor, SOURCE_NAME))
        for pdv_id, station_signals in signals.items():
            _replace_signals(cursor, known[pdv_id]["poi_id"], SIGNALS_FROM_STATE, station_signals, removed)
        cnx.commit()
    except Exception:
        cnx.rollback()
        raise
    finally:
        cursor.close()
        MySQLUtils.disconnect(cnx)


def mark_prices_read(read_at) -> None:
    """Note la date du rafraîchissement national des prix (sources.lu_le), lue par GET /api/step1/cities."""
    cnx = MySQLUtils.connect()
    cursor = cnx.cursor()
    try:
        source_id = get_or_create_source(cursor, SOURCE_NAME)
        cursor.execute("UPDATE sources SET lu_le = %s WHERE id = %s", (read_at, source_id))
        cnx.commit()
    finally:
        cursor.close()
        MySQLUtils.disconnect(cnx)


def prices_read_at():
    """La date du dernier rafraîchissement national des prix, ou None s'il n'a jamais eu lieu."""
    cnx = MySQLUtils.connect()
    cursor = cnx.cursor()
    try:
        cursor.execute("SELECT lu_le FROM sources WHERE name = %s", (SOURCE_NAME,))
        row = cursor.fetchone()
        return row[0] if row else None
    finally:
        cursor.close()
        MySQLUtils.disconnect(cnx)


def known_stations() -> dict:
    """{identifiant de l'État: (poi_id, osm_element, lien_osm, nom, latitude, longitude, marque)} des stations en base."""
    cnx = MySQLUtils.connect()
    cursor = cnx.cursor(dictionary=True)
    cursor.execute(
        """
        SELECT sc.pdv_id, sc.poi_id, sc.osm_element, sc.lien_osm, sc.marque, p.name, p.latitude, p.longitude
        FROM stations_carburant sc JOIN poi p ON p.id = sc.poi_id
        """)
    rows = {row["pdv_id"]: row for row in cursor.fetchall()}
    cursor.close()
    MySQLUtils.disconnect(cnx)
    return rows
