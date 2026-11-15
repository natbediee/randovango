"""
Relit dans OSM, en une fois, l'étiquette access (à qui c'est ouvert) et fee (payant ou non) de toutes les toilettes
et douches d'OSM déjà en base (issue #248).

POURQUOI
Depuis #193, l'étape 4 cache les toilettes et douches réservées aux clients (customers, private, no) et ne montre
« Vérifié » que celles marquées access=yes. Mais l'étiquette n'est lue qu'au passage OSM d'une commune : une commune
pas encore repassée montre toutes ses toilettes « non vérifié », et ses toilettes customers restent montrées.
Le passage d'une commune ne lit en plus qu'un carré de ±0,05° autour de son centre, plus petit que les 5 km de
l'étape 4. Ici, on relit chaque toilette par son identifiant OSM : rien ne dépend plus des communes.

COMMENT
    1. les toilettes et douches d'OSM de la base (load_facilities) ;
    2. leurs objets OSM, par identifiant, en paquets de 400 (api_osm.extract_osm_by_ids, gratuit) ;
    3. pour chacune, trois cas (sort_facilities) :
         lue      : l'objet est encore une toilette ou une douche, ses étiquettes sont écrites (load_poi.save_public_access) ;
         absente  : OSM a répondu, mais l'objet n'existe plus ou n'est plus une toilette. Elle n'est pas cachée d'office :
                    un signal « absent_osm » l'envoie en relecture dans /supervision (l'humain décide), et l'étape 4 la
                    montre « non vérifié » en attendant. Ses étiquettes ne sont pas touchées ;
         non lue  : le paquet a échoué même après les reprises. Rien n'est conclu ni écrit : il suffit de relancer.

UTILISATION (dans le conteneur backend, depuis /usr/src/app) :
    python -m etl.etl_toilettes --essai     # lit OSM, n'écrit rien : affiche ce qui changerait
    python -m etl.etl_toilettes             # écrit les étiquettes et les signaux
"""
import argparse
from collections import Counter

from etl.extract.api_osm import extract_osm_by_ids
from etl.load.load_poi import save_public_access
from etl.load.load_poi_checks import save_signal
from etl.transform.transform_osm import PUBLIC_FACILITY_TYPES, pick_osm_element, public_access
from utils.db_utils import MySQLUtils
from utils.logger_util import LoggerUtil

logger = LoggerUtil.get_logger("etl_toilettes")

NO_TAG = "(aucune)"     # comment le bilan écrit une étiquette access absente


def load_facilities() -> list:
    """
    Les toilettes et douches d'OSM de la base, une ligne par lieu : id, nom, identifiant OSM, position, type
    (toilets ou shower) et étiquette access déjà connue. Les lieux masqués sont relus aussi : c'est sans danger,
    seules leurs étiquettes changent.
    """
    marks = ",".join(["%s"] * len(PUBLIC_FACILITY_TYPES))
    connection = MySQLUtils.connect()
    cursor = connection.cursor(dictionary=True)
    try:
        # MIN(sv.category) : un lieu classé à la fois toilette et douche ne compte qu'une fois.
        cursor.execute(
            f"""SELECT p.id, p.name, p.original_id, p.latitude, p.longitude, p.acces_osm,
                       MIN(sv.category) AS type
                FROM poi p
                JOIN sources s ON s.id = p.source_id AND s.name = 'osm'
                JOIN poi_service ps ON ps.poi_id = p.id
                JOIN services sv ON sv.id = ps.service_id AND sv.category IN ({marks})
                GROUP BY p.id, p.name, p.original_id, p.latitude, p.longitude, p.acces_osm
                ORDER BY p.id""", PUBLIC_FACILITY_TYPES)
        return cursor.fetchall()
    finally:
        cursor.close()
        MySQLUtils.disconnect(connection)


def is_still_facility(element: dict | None) -> bool:
    """L'objet OSM existe et reste une toilette ou une douche (amenity=toilets ou shower)."""
    return element is not None and element.get("tags", {}).get("amenity") in PUBLIC_FACILITY_TYPES


def sort_facilities(facilities: list, elements: dict, unread: set) -> tuple:
    """
    Range chaque toilette de la base dans l'un des trois cas : (lues, absentes, non lues).
    Une toilette lue est renvoyée avec ses nouvelles étiquettes : {**toilette, "access": ..., "payant": ...}.
    elements et unread viennent de extract_osm_by_ids.
    """
    read, absent, not_read = [], [], []
    for facility in facilities:
        osm_id = str(facility["original_id"])
        if osm_id in unread:
            not_read.append(facility)
            continue
        # Un même numéro peut être un node et un way : on garde l'objet qui est à l'emplacement de la toilette.
        element = pick_osm_element(elements.get(osm_id, []), float(facility["latitude"]), float(facility["longitude"]))
        if is_still_facility(element):
            read.append({**facility, **public_access(element["tags"])})
        else:
            absent.append(facility)
    return read, absent, not_read


def count_changes(read: list) -> Counter:
    """Le bilan avant/après : combien de toilettes passent de telle étiquette access à telle autre."""
    return Counter((facility["acces_osm"] or NO_TAG, facility["access"] or NO_TAG) for facility in read)


def write_results(read: list, absent: list) -> None:
    """Écrit les étiquettes des toilettes lues et un signal « absent_osm » pour les absentes, en une transaction."""
    connection = MySQLUtils.connect()
    cursor = connection.cursor()
    try:
        for facility in read:
            save_public_access(cursor, facility["id"], facility)
        for facility in absent:
            save_signal(cursor, facility["id"], "osm", "absent_osm", {"nom": facility["name"]})
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        MySQLUtils.disconnect(connection)


def print_report(read: list, absent: list, not_read: list, dry_run: bool) -> None:
    """Affiche le bilan : les changements d'étiquette, puis les absentes et les non lues."""
    title = "essai, rien n'est écrit" if dry_run else "passage réel"
    print(f"\n=== Toilettes et douches ({title}) ===")
    print(f"{len(read)} lues, {len(absent)} absentes d'OSM, {len(not_read)} non lues")
    print("\nÉtiquette access, avant -> après :")
    for (before, after), count in sorted(count_changes(read).items()):
        print(f"  {before} -> {after} : {count}")
    print(f"\nPayantes (fee=yes) : {sum(1 for facility in read if facility['payant'] == 1)}")
    if absent:
        print("\nAbsentes d'OSM (signal « absent_osm » à relire dans /supervision) :")
        for facility in absent:
            print(f"  poi {facility['id']} | OSM {facility['original_id']} | {facility['name']}")
    if not_read:
        print(f"\n{len(not_read)} non lues : rien n'est écrit pour elles, relancer le passage.")


def run(dry_run: bool = False) -> tuple:
    """Le passage complet. Renvoie (lues, absentes, non lues) ; en essai, rien n'est écrit."""
    facilities = load_facilities()
    logger.info(f"[toilettes] {len(facilities)} toilettes et douches d'OSM à relire")
    elements, unread = extract_osm_by_ids(sorted({str(facility["original_id"]) for facility in facilities}))
    read, absent, not_read = sort_facilities(facilities, elements, unread)
    if not dry_run:
        write_results(read, absent)
    print_report(read, absent, not_read, dry_run)
    return read, absent, not_read


def main() -> None:
    parser = argparse.ArgumentParser(description="Relit l'étiquette access de toutes les toilettes et douches d'OSM")
    parser.add_argument("--essai", action="store_true", help="lit OSM mais n'écrit rien : affiche ce qui changerait")
    args = parser.parse_args()
    run(dry_run=args.essai)


if __name__ == "__main__":
    main()
