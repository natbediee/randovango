"""
Script ponctuel : comble la colonne `address` sur `poi`, `spots` et `hikes`
(point de départ) via géocodage inverse (Nominatim). Respecte la limite d'usage
(max 1 req/s).
Interruptible et rejouable : ne traite que les lignes encore à NULL.

Optimisation : géocode une seule fois par localisation unique (arrondissement
à 3 décimales ≈ 111 m) et propage l'adresse à toutes les lignes proches.
"""
import time
from collections import defaultdict

from utils.db_utils import MySQLUtils
from utils.geo_utils import get_address_from_coordinates
from utils.logger_util import LoggerUtil

logger = LoggerUtil.get_logger("etl_backfill_addresses")

DELAY_BETWEEN_CALLS_S = 1.1


def _backfill_table(table: str, lat_col: str = "latitude", lon_col: str = "longitude"):
    # hikes stocke le point de départ dans start_latitude/start_longitude ; poi et
    # spots dans latitude/longitude. On paramètre donc les colonnes de coordonnées.
    cnx = MySQLUtils.connect()
    cursor = cnx.cursor(dictionary=True)
    cursor.execute(
        f"SELECT id, {lat_col} AS lat, {lon_col} AS lon FROM {table} WHERE address IS NULL"
        f" AND {lat_col} IS NOT NULL AND {lon_col} IS NOT NULL"
    )
    rows = cursor.fetchall()
    cursor.close()
    MySQLUtils.disconnect(cnx)

    # Regrouper les IDs par localisation arrondie (≈ 111 m)
    location_groups: dict[tuple, list[int]] = defaultdict(list)
    for row in rows:
        key = (round(float(row["lat"]), 3), round(float(row["lon"]), 3))
        location_groups[key].append(row["id"])

    total_locations = len(location_groups)
    total_rows = len(rows)
    logger.info(
        f"[backfill:{table}] {total_rows} ligne(s), "
        f"{total_locations} localisation(s) unique(s) → "
        f"{total_rows - total_locations} appel(s) économisé(s)"
    )

    done_locs, skipped_locs, updated_rows = 0, 0, 0

    for i, ((lat, lon), ids) in enumerate(location_groups.items()):
        address = get_address_from_coordinates(lat, lon)
        time.sleep(DELAY_BETWEEN_CALLS_S)

        if not address:
            skipped_locs += 1
            continue

        cnx = MySQLUtils.connect()
        cursor = cnx.cursor()
        fmt = ",".join(["%s"] * len(ids))
        cursor.execute(
            f"UPDATE {table} SET address = %s WHERE id IN ({fmt})",
            (address, *ids),
        )
        cnx.commit()
        cursor.close()
        MySQLUtils.disconnect(cnx)

        done_locs += 1
        updated_rows += len(ids)

        if (i + 1) % 50 == 0:
            logger.info(
                f"[backfill:{table}] {i+1}/{total_locations} localisations"
                f" ({updated_rows} ligne(s) mises à jour)"
            )

    logger.info(
        f"[backfill:{table}] Terminé : {updated_rows} ligne(s) mises à jour"
        f" via {done_locs} géocodage(s), {skipped_locs} localisation(s) sans résultat"
    )


def main():
    _backfill_table("poi")
    _backfill_table("spots")
    _backfill_table("hikes", lat_col="start_latitude", lon_col="start_longitude")


if __name__ == "__main__":
    main()
