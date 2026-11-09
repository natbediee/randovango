"""
La commune officielle de chaque ville de la table cities : colonnes commune et insee.

POURQUOI
Le nom d'une ville vient de Nominatim, qui donne le lieu le plus proche du départ de la rando : parfois un village,
pas une commune. La pointe de Corsen est rangée à Trézien, qui est en Plouarzel. Les agents et l'étape 4 ont besoin de
la commune : c'est elle qu'écrivent les adresses (« 29810 Plouarzel ») et qu'interroge le registre des entreprises.

CE QUE FAIT LE SCRIPT
Il demande à geo.api.gouv.fr (gratuit, officiel) la commune qui contient la position de la ville, et remplit les deux
colonnes. Il ne change ni le nom, ni la position, ni aucune autre table : rien ne bouge dans les randos, les POI,
les spots ou les plans. Une ville déjà remplie n'est pas réécrite.

    python -m etl.fill_communes --ville Trézien --essai     # montre, n'écrit rien
    python -m etl.fill_communes --ville Trézien
    python -m etl.fill_communes --toutes --essai
"""
import argparse
import json
import time

from utils.db_utils import MySQLUtils
from utils.geo_utils import get_commune_from_coordinates
from utils.logger_util import LoggerUtil

logger = LoggerUtil.get_logger("fill_communes")

PAUSE_SECONDS = 0.2     # geo.api.gouv.fr limite le nombre de requêtes par seconde


def cities_to_fill(cursor, names: list | None) -> list:
    """Les villes sans commune : celles nommées, ou toutes."""
    query = "SELECT id, name, latitude, longitude FROM cities WHERE insee IS NULL"
    if names:
        query += f" AND name IN ({','.join(['%s'] * len(names))})"
    cursor.execute(query + " ORDER BY id", tuple(names or ()))
    return [dict(zip(("id", "name", "latitude", "longitude"), row)) for row in cursor.fetchall()]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--ville", action="append", help="Nom d'une ville de la table cities (répétable)")
    target.add_argument("--toutes", action="store_true", help="Toutes les villes sans commune")
    parser.add_argument("--essai", action="store_true", help="Montre ce qui serait écrit, n'écrit rien")
    args = parser.parse_args()

    connection = MySQLUtils.connect()
    cursor = connection.cursor()
    for city in cities_to_fill(cursor, args.ville):
        time.sleep(PAUSE_SECONDS)
        commune, insee = get_commune_from_coordinates(city["latitude"], city["longitude"])
        print(json.dumps({"id": city["id"], "ville": city["name"], "commune": commune, "insee": insee,
                          "differente": bool(commune) and commune != city["name"]}, ensure_ascii=False))
        if not insee or args.essai:
            continue
        cursor.execute("UPDATE cities SET commune = %s, insee = %s WHERE id = %s AND insee IS NULL",
                       (commune, insee, city["id"]))
        connection.commit()
        logger.info(f"[communes] {city['name']} (id {city['id']}) : {commune} {insee}")
    cursor.close()
    MySQLUtils.disconnect(connection)


if __name__ == "__main__":
    main()
