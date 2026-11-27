"""
Retire de la base les stations-service d'OSM chargées comme services, à lancer une fois.

POURQUOI
Avant, l'étape OSM chargeait les stations-service comme les autres lieux (table poi, service « fuel »). L'étape 4 ne les
a jamais montrées : seules les stations du fichier de l'État le sont, avec le nom et la marque d'OSM. Elles ne
servaient qu'à la règle des doublons, qui les masquait derrière la station de l'État (244 fusions automatiques au
27 novembre 2026). Désormais l'étape OSM les range dans osm_fuel_stations, où l'étape des carburants les relit :
celles qui restent dans poi n'ont plus de raison d'y être. Aucune décision humaine ne porte sur elles.

CE QUE FAIT LE SCRIPT, dans une seule transaction
1. Un jour de voyage qui contient une de ces stations pointe désormais sur la station de l'État qui a le même objet OSM
   (stations_carburant.osm_element). Sans station de l'État, la station est retirée de ce jour : l'étape 4 ne la
   montrait déjà plus.
2. Les stations sont supprimées avec ce qui leur est rattaché : décisions de la règle, signaux, vérifications, liens
   aux villes et aux services.

À lancer après la fusion de la branche dans main : tant que main tourne avec l'ancienne étape OSM, il les remettrait.
Le script peut être relancé sans risque : la seconde fois, il ne trouve plus rien.

UTILISATION (depuis backend/) :
    python -m etl.remove_osm_fuel_services --essai     # n'écrit rien : dit ce qui serait fait
    python -m etl.remove_osm_fuel_services
"""
import argparse

from utils.db_utils import MySQLUtils
from utils.logger_util import LoggerUtil

logger = LoggerUtil.get_logger("etl_carburants")

# Les tables rattachées à un lieu par poi_id, vidées avant le lieu lui-même (clés étrangères).
LINKED_TABLES = ("poi_checks", "poi_signals", "poi_service", "histo_poi", "trip_day_pois")


def osm_fuel_ids(cursor) -> list:
    """Les identifiants des lieux d'OSM rangés sous le service « fuel »."""
    cursor.execute(
        """
        SELECT DISTINCT p.id FROM poi p
        JOIN sources s ON s.id = p.source_id
        JOIN poi_service ps ON ps.poi_id = p.id
        JOIN services sv ON sv.id = ps.service_id
        WHERE s.name = 'osm' AND sv.category = 'fuel'
        ORDER BY p.id
        """)
    return [row[0] for row in cursor.fetchall()]


def trip_links(cursor, ids: list) -> list:
    """
    [(jour de voyage, station OSM, station de l'État ou None)] des voyages qui contiennent une de ces stations.
    original_id d'un lieu OSM ne garde que le numéro de l'objet (« 582223754 »), osm_element le type en plus
    (« node/582223754 ») : on compare le numéro seul.
    """
    marks = ", ".join(["%s"] * len(ids))
    cursor.execute(
        f"""
        SELECT t.trip_day_id, t.poi_id, MIN(sc.poi_id)
        FROM trip_day_pois t
        JOIN poi p ON p.id = t.poi_id
        LEFT JOIN stations_carburant sc ON SUBSTRING_INDEX(sc.osm_element, '/', -1) = p.original_id
        WHERE t.poi_id IN ({marks})
        GROUP BY t.trip_day_id, t.poi_id
        """,
        ids)
    return cursor.fetchall()


def move_trip_links(cursor, links: list) -> None:
    """Chaque jour de voyage pointe sur la station de l'État quand elle existe ; l'ancien lien part avec la station."""
    for trip_day_id, _, state_poi_id in links:
        if state_poi_id is not None:
            # IGNORE : le voyageur a peut-être déjà ajouté la station de l'État à ce jour-là.
            cursor.execute("INSERT IGNORE INTO trip_day_pois (trip_day_id, poi_id) VALUES (%s, %s)",
                           (trip_day_id, state_poi_id))


def delete_places(cursor, ids: list) -> None:
    """Supprime les lieux et tout ce qui leur est rattaché : d'abord les tables liées, puis les décisions, puis poi."""
    marks = ", ".join(["%s"] * len(ids))
    for table in LINKED_TABLES:
        cursor.execute(f"DELETE FROM {table} WHERE poi_id IN ({marks})", ids)
    cursor.execute(f"DELETE FROM decisions WHERE objet_type = 'poi' AND objet_id IN ({marks})", ids)
    cursor.execute(f"DELETE FROM poi WHERE id IN ({marks})", ids)


def remove_osm_fuel_services(dry_run: bool = False) -> int:
    """Renvoie le nombre de stations OSM retirées (ou qui le seraient)."""
    with MySQLUtils.open_cursor() as (cnx, cursor):
        ids = osm_fuel_ids(cursor)
        if not ids:
            print("Aucune station-service d'OSM dans les services : rien à faire.")
            return 0
        links = trip_links(cursor, ids)
        moved = [link for link in links if link[2] is not None]
        print(f"{len(ids)} stations-service d'OSM à retirer ; {len(links)} jours de voyage en contiennent : "
              f"{len(moved)} passent sur la station de l'État, {len(links) - len(moved)} la perdent.")
        for trip_day_id, poi_id, state_poi_id in links:
            print(f"  jour {trip_day_id} : station {poi_id} → {state_poi_id or 'retirée'}")
        if dry_run:
            return len(ids)
        try:
            move_trip_links(cursor, links)
            delete_places(cursor, ids)
            cnx.commit()
        except Exception:
            cnx.rollback()
            raise
    logger.info(f"[Load] : {len(ids)} stations-service d'OSM retirées des services")
    return len(ids)


def main() -> None:
    parser = argparse.ArgumentParser(description="Retire les stations-service d'OSM chargées comme services")
    parser.add_argument("--essai", action="store_true", help="n'écrit rien en base, dit ce qui serait fait")
    args = parser.parse_args()
    remove_osm_fuel_services(dry_run=args.essai)


if __name__ == "__main__":
    main()
