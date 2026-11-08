"""
Chargement des stations-service de l'État : poi, stations_carburant et prix_carburants. Les tables sont créées dans
db_init/db_randovango.py.

Une station est un poi de la source « prix-carburants » (original_id = identifiant de l'État), lié au service « fuel » :
l'étape 4 la range donc dans l'onglet gasoil sans rien changer. Son nom et sa position sont remis à jour à chaque
passage, depuis OSM ; une correction humaine passe par la table decisions et n'est jamais écrasée ici.

Les prix d'une station sont remplacés en bloc : la table garde exactement ce que dit le dernier fichier.
"""
import json

from etl.load.load_poi import get_or_create_source, insert_histo_poi, insert_service_and_link
from utils.db_utils import MySQLUtils
from utils.logger_util import LoggerUtil

logger = LoggerUtil.get_logger("etl_carburants")

SOURCE_NAME = "prix-carburants"
FUEL_SERVICE = "fuel"
STATION_COLUMNS = ("pdv_id", "osm_element", "lien_osm", "marque", "adresse_etat", "code_postal", "ville_etat",
                   "latitude_etat", "longitude_etat", "route", "automate_24_24", "horaires", "services",
                   "fermeture_type", "fermeture_debut", "fermeture_fin", "lu_le")
JSON_COLUMNS = ("horaires", "services")


def _upsert_poi(cursor, source_id: int, pdv_id: str, poi: dict) -> int:
    cursor.execute(
        """
        INSERT INTO poi (original_id, name, latitude, longitude, address, source_id, verifie)
        VALUES (%s, %s, %s, %s, %s, %s, 1)
        ON DUPLICATE KEY UPDATE name = VALUES(name), latitude = VALUES(latitude), longitude = VALUES(longitude),
                                address = VALUES(address)
        """,
        (pdv_id, poi["name"], poi["latitude"], poi["longitude"], poi["address"], source_id))
    cursor.execute("SELECT id FROM poi WHERE original_id = %s AND source_id = %s", (pdv_id, source_id))
    return cursor.fetchone()[0]


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
        for row in rows:
            poi_id = _upsert_poi(cursor, source_id, row["station"]["pdv_id"], row["poi"])
            insert_service_and_link(cursor, poi_id, FUEL_SERVICE)
            if city_name:
                insert_histo_poi(cursor, poi_id, city_name)
            _upsert_station(cursor, poi_id, row["station"])
            _replace_prices(cursor, poi_id, row["prix"])
        cnx.commit()
    except Exception:
        cnx.rollback()
        raise
    finally:
        cursor.close()
        MySQLUtils.disconnect(cnx)
    logger.info(f"[Load] : {len(rows)} stations chargées{f' pour {city_name}' if city_name else ''}")
    return len(rows)


def known_stations() -> dict:
    """{identifiant de l'État: (osm_element, lien_osm, nom, latitude, longitude, marque)} des stations déjà en base."""
    cnx = MySQLUtils.connect()
    cursor = cnx.cursor(dictionary=True)
    cursor.execute(
        """
        SELECT sc.pdv_id, sc.osm_element, sc.lien_osm, sc.marque, p.name, p.latitude, p.longitude
        FROM stations_carburant sc JOIN poi p ON p.id = sc.poi_id
        """)
    rows = {row["pdv_id"]: row for row in cursor.fetchall()}
    cursor.close()
    MySQLUtils.disconnect(cnx)
    return rows
