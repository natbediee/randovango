"""
Les adresses et les noms de ville déjà en base, convertis en commune (issue #184, étape 2).

POURQUOI
Depuis l'étape 1, l'appli ne propose plus que des communes. Mais environ 290 services et 105 spots portent encore un
lieu-dit après leur code postal (« 29810 Trézien », « 29880 Lilia »), écrit avant que les chargements ne convertissent
les noms dès leur arrivée : la supervision les rangeait sous Trézien, et l'étape 4 ne les voyait pas depuis Plouarzel.

CE QUE FAIT LE SCRIPT
    1. L'adresse de chaque service (poi) et de chaque spot passe par geo_utils.address_with_commune :
       « rue, 29810 Trézien » devient « rue, Trézien, 29810 Plouarzel ». Le lieu-dit reste lisible sur sa ligne.
    2. Le nom de ville d'un spot (city_label) devient sa commune : « Lilia » devient « Plouguerneau ».
Une adresse qu'un humain a corrigée dans la supervision n'est pas touchée : sa décision prime. Rien d'autre ne change.
Relancé, le script ne refait rien : une adresse déjà convertie reste telle quelle.

    python -m etl.convert_addresses_to_communes --essai     # liste et compte, n'écrit rien
    python -m etl.convert_addresses_to_communes
"""
import argparse
import json
from collections import Counter

from services.supervision.services_edit import human_fields
from utils.db_utils import MySQLUtils
from utils.geo_utils import address_with_commune, commune_of_town
from utils.logger_util import LoggerUtil

logger = LoggerUtil.get_logger("convert_addresses_to_communes")

# Une adresse qui finit par un code postal et un nom : les seules que la conversion peut changer.
WITH_POSTCODE = "address REGEXP '[0-9]{5} [^,]+$'"


def show(change: dict) -> None:
    """Écrit une ligne du bilan : ce qui change, pour la relecture de l'essai."""
    print(json.dumps(change, ensure_ascii=False))


def convert_poi_addresses(cursor, trial: bool) -> Counter:
    """Convertit l'adresse des services. Renvoie le compte : convertis, laissés à un humain."""
    summary = Counter()
    cursor.execute(f"SELECT id, address, latitude, longitude FROM poi WHERE {WITH_POSTCODE} ORDER BY id")
    for poi in cursor.fetchall():
        new = address_with_commune(poi["address"], poi["latitude"], poi["longitude"])
        if new == poi["address"]:
            continue
        if "address" in human_fields(cursor, poi["id"]):
            summary["services laissés (adresse corrigée par un humain)"] += 1
            continue
        summary["services convertis"] += 1
        show({"service": poi["id"], "avant": poi["address"], "après": new})
        if not trial:
            # « AND address = » : une adresse changée entre-temps (une correction humaine) n'est pas écrasée.
            cursor.execute("UPDATE poi SET address = %s WHERE id = %s AND address = %s", (new, poi["id"], poi["address"]))
    return summary


def spot_label(spot: dict) -> str | None:
    """Le nom de ville d'un spot converti en commune, ou le même s'il est déjà une commune ou si on ne sait pas."""
    if not spot["city_label"] or not spot["postal_code"]:
        return spot["city_label"]
    commune = commune_of_town(spot["postal_code"], spot["city_label"], spot["latitude"], spot["longitude"])
    return commune or spot["city_label"]


def convert_spots(cursor, trial: bool) -> Counter:
    """Convertit l'adresse et le nom de ville des spots. Renvoie le compte des spots convertis."""
    summary = Counter()
    cursor.execute("""
        SELECT id, address, city_label, postal_code, latitude, longitude FROM spots
        WHERE address IS NOT NULL OR city_label IS NOT NULL ORDER BY id
    """)
    for spot in cursor.fetchall():
        address = address_with_commune(spot["address"], spot["latitude"], spot["longitude"])
        label = spot_label(spot)
        if (address, label) == (spot["address"], spot["city_label"]):
            continue
        summary["spots convertis"] += 1
        show({"spot": spot["id"], "avant": [spot["address"], spot["city_label"]], "après": [address, label]})
        if not trial:
            cursor.execute("UPDATE spots SET address = %s, city_label = %s WHERE id = %s",
                           (address, label, spot["id"]))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--essai", action="store_true", help="Liste et compte ce qui changerait, n'écrit rien")
    args = parser.parse_args()
    # « with » : la connexion se ferme à la sortie du bloc, même en cas d'erreur (issue #206).
    # buffered : human_fields pose sa question pendant qu'on parcourt les lignes déjà lues.
    with MySQLUtils.open_cursor(dictionary=True, buffered=True) as (connection, cursor):
        summary = convert_poi_addresses(cursor, args.essai) + convert_spots(cursor, args.essai)
        if not args.essai:
            connection.commit()
    print(json.dumps({"essai": args.essai, **summary}, ensure_ascii=False))
    logger.info(f"[communes] adresses{' (essai)' if args.essai else ''} : {dict(summary)}")


if __name__ == "__main__":
    main()
