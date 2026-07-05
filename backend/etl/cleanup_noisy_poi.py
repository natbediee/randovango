"""
Script ponctuel : supprime les POI patrimoniaux trop génériques/granulaires
(temple, fortification, site archéologique, croix, lavoir, place_of_worship,
site touristique, "yes") importés via Wikidata avant que les classes
Église/Chapelle et Ruines ne soient retirées de la requête SPARQL.
Sans intérêt pour un usage van life et ils noyaient les vraies attractions.
"""
from utils.db_utils import MySQLUtils
from utils.logger_util import LoggerUtil

logger = LoggerUtil.get_logger("etl_cleanup")

NOISY_CATEGORIES = [
    'temple',
    'fortification',
    'site archéologique',
    'croix',
    'lavoir',
    'yes',
    'place_of_worship',
    'site touristique',
    'temple, site archéologique',
    'site archéologique, fortification',
]


def main():
    cnx = MySQLUtils.connect()
    cursor = cnx.cursor()

    placeholders = ', '.join(['%s'] * len(NOISY_CATEGORIES))

    cursor.execute(
        f"""
        SELECT DISTINCT ps.poi_id
        FROM poi_service ps
        JOIN services s ON ps.service_id = s.id
        WHERE s.category IN ({placeholders})
        """,
        NOISY_CATEGORIES
    )
    poi_ids = [row[0] for row in cursor.fetchall()]
    logger.info(f"[cleanup] {len(poi_ids)} POI à supprimer (catégories patrimoniales)")

    if not poi_ids:
        cursor.close()
        MySQLUtils.disconnect(cnx)
        return

    id_placeholders = ', '.join(['%s'] * len(poi_ids))

    cursor.execute(f"DELETE FROM trip_day_pois WHERE poi_id IN ({id_placeholders})", poi_ids)
    logger.info(f"[cleanup] {cursor.rowcount} lien(s) trip_day_pois supprimé(s)")

    cursor.execute(f"DELETE FROM histo_poi WHERE poi_id IN ({id_placeholders})", poi_ids)
    logger.info(f"[cleanup] {cursor.rowcount} ligne(s) histo_poi supprimée(s)")

    cursor.execute(f"DELETE FROM poi_service WHERE poi_id IN ({id_placeholders})", poi_ids)
    logger.info(f"[cleanup] {cursor.rowcount} lien(s) poi_service supprimé(s)")

    cursor.execute(f"DELETE FROM poi WHERE id IN ({id_placeholders})", poi_ids)
    logger.info(f"[cleanup] {cursor.rowcount} POI supprimé(s)")

    cursor.execute(f"DELETE FROM services WHERE category IN ({placeholders})", NOISY_CATEGORIES)
    logger.info(f"[cleanup] {cursor.rowcount} service(s) orphelin(s) supprimé(s)")

    cnx.commit()
    cursor.close()
    MySQLUtils.disconnect(cnx)


if __name__ == "__main__":
    main()
