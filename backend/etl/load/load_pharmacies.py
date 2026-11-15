"""
Chargement des pharmacies de FINESS (carte #194), dans les tables des services, sans table à part.

Une pharmacie est un poi de la source « finess » (original_id = numéro FINESS), lié au service « pharmacy » : l'étape 4
la range donc dans l'onglet Urgences sans rien changer. Son nom, son adresse et sa position sont remis à jour à chaque
passage, sauf ce qu'un humain a corrigé dans /supervision (table decisions, non annulée), comme pour les stations.

Une pharmacie fermée dans FINESS, ou sortie du fichier, est masquée (poi.masque = 1) : l'État le dit, il n'y a rien à
relire. Elle n'est jamais réaffichée par ce chargement. Sa date de fermeture n'est pas gardée : elle reste dans FINESS.
"""
from etl.load.load_carburants import human_fields
from etl.load.load_poi import get_or_create_source, insert_histo_poi, insert_service_and_link
from utils.db_utils import MySQLUtils
from utils.geo_utils import address_with_commune, get_bounding_box
from utils.logger_util import LoggerUtil

logger = LoggerUtil.get_logger("etl_pharmacies")

SOURCE_NAME = "finess"
OSM_SOURCE = "osm"
PHARMACY_SERVICE = "pharmacy"
POI_COLUMNS = ("name", "latitude", "longitude", "address")


def osm_pharmacies_near(latitude: float, longitude: float, distance_km: float) -> list:
    """Les pharmacies OSM affichées du carré autour du point : celles dont on peut prendre le nom."""
    south, west, north, east = get_bounding_box(latitude, longitude, distance_km)
    cnx = MySQLUtils.connect()
    cursor = cnx.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT p.id AS poi_id, p.name, p.latitude, p.longitude
            FROM poi p
            JOIN poi_service ps ON ps.poi_id = p.id
            JOIN services s ON s.id = ps.service_id
            JOIN sources src ON src.id = p.source_id
            WHERE s.category = %s AND src.name = %s AND p.masque = 0
            AND p.latitude BETWEEN %s AND %s AND p.longitude BETWEEN %s AND %s
            """,
            (PHARMACY_SERVICE, OSM_SOURCE, south, north, west, east))
        return cursor.fetchall()
    finally:
        cursor.close()
        MySQLUtils.disconnect(cnx)


def _upsert_poi(cursor, source_id: int, finess: str, poi: dict, protected: dict) -> int:
    """Crée le poi d'une pharmacie, ou remet à jour ses colonnes, sauf celles qu'un humain a corrigées (protected)."""
    # La commune après le code postal, le lieu-dit sur sa propre ligne (issue #184) : « ..., 29760 Penmarch ».
    poi = {**poi, "address": address_with_commune(poi["address"], poi["latitude"], poi["longitude"])}
    cursor.execute("SELECT id FROM poi WHERE original_id = %s AND source_id = %s", (finess, source_id))
    found = cursor.fetchone()
    if found is None:
        cursor.execute(
            """
            INSERT INTO poi (original_id, name, latitude, longitude, address, source_id, verifie)
            VALUES (%s, %s, %s, %s, %s, %s, 1)
            """,
            (finess, poi["name"], poi["latitude"], poi["longitude"], poi["address"], source_id))
        return cursor.lastrowid
    poi_id = found[0]
    columns = [column for column in POI_COLUMNS if column not in protected.get(poi_id, set())]
    if columns:
        cursor.execute(f"UPDATE poi SET {', '.join(f'{c} = %s' for c in columns)} WHERE id = %s",
                       (*(poi[c] for c in columns), poi_id))
    return poi_id


def load_pharmacy_rows(rows: list, city_name: str) -> int:
    """Charge les pharmacies ouvertes d'une ville. Une seule transaction : tout ou rien."""
    if not rows:
        return 0
    cnx = MySQLUtils.connect()
    cursor = cnx.cursor()
    try:
        source_id = get_or_create_source(cursor, SOURCE_NAME)
        protected = human_fields(cursor, source_id)
        for row in rows:
            poi_id = _upsert_poi(cursor, source_id, row["finess"], row["poi"], protected)
            insert_service_and_link(cursor, poi_id, PHARMACY_SERVICE)
            insert_histo_poi(cursor, poi_id, city_name)
        cnx.commit()
    except Exception:
        cnx.rollback()
        raise
    finally:
        cursor.close()
        MySQLUtils.disconnect(cnx)
    logger.info(f"[Load] : {len(rows)} pharmacies chargées pour {city_name}")
    return len(rows)


def known_pharmacies() -> dict:
    """{numéro FINESS: poi_id} des pharmacies déjà en base : les poi de la source finess."""
    cnx = MySQLUtils.connect()
    cursor = cnx.cursor()
    try:
        cursor.execute("SELECT p.original_id, p.id FROM poi p JOIN sources src ON src.id = p.source_id "
                       "WHERE src.name = %s", (SOURCE_NAME,))
        return dict(cursor.fetchall())
    finally:
        cursor.close()
        MySQLUtils.disconnect(cnx)


def hide_closed(closed: dict, known: dict) -> int:
    """
    Masque les pharmacies fermées (les numéros FINESS de closed) ; known : {numéro FINESS: poi_id}.
    Renvoie le nombre de pharmacies masquées par ce passage.
    """
    if not closed:
        return 0
    cnx = MySQLUtils.connect()
    cursor = cnx.cursor()
    hidden = 0
    try:
        for finess in closed:
            cursor.execute("UPDATE poi SET masque = 1 WHERE id = %s AND masque = 0", (known[finess],))
            hidden += cursor.rowcount
        cnx.commit()
    except Exception:
        cnx.rollback()
        raise
    finally:
        cursor.close()
        MySQLUtils.disconnect(cnx)
    logger.info(f"[Load] : {hidden} pharmacies fermées masquées")
    return hidden


def mark_pharmacies_read(read_at) -> None:
    """
    Note la date de la dernière relecture complète de FINESS (sources.lu_le de la source finess, carte #241) :
    api/routers/step1.py ne relance pas la relecture le même jour.
    """
    cnx = MySQLUtils.connect()
    cursor = cnx.cursor()
    try:
        source_id = get_or_create_source(cursor, SOURCE_NAME)
        cursor.execute("UPDATE sources SET lu_le = %s WHERE id = %s", (read_at, source_id))
        cnx.commit()
    finally:
        cursor.close()
        MySQLUtils.disconnect(cnx)


def pharmacies_read_at():
    """La date de la dernière relecture complète de FINESS, ou None si elle n'a jamais eu lieu."""
    cnx = MySQLUtils.connect()
    cursor = cnx.cursor()
    try:
        cursor.execute("SELECT lu_le FROM sources WHERE name = %s", (SOURCE_NAME,))
        row = cursor.fetchone()
        return row[0] if row else None
    finally:
        cursor.close()
        MySQLUtils.disconnect(cnx)
