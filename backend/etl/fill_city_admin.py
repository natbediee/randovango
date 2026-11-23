"""
La commune, le département, la région et le pays des villes de la table cities qui en manquent (issue #318).

POURQUOI
Le 23 novembre 2026, un envoi de 98 randos a créé 71 villes d'un coup. Le département et la région venaient alors de
Nominatim, qui a refusé la plupart des appels (« trop d'appels ») : 51 villes sont restées sans département ni région
(Champagne, Le Mung, Grues...), et La Jonchère sans commune. Or l'agent des services cherche « Champagne, Charente-
Maritime » : sans département, il cherchait « Champagne, France », au risque de tomber sur un homonyme.

CE QUE FAIT LE SCRIPT
Pour chaque ville à qui il manque l'une de ces colonnes :
    1. sans code INSEE, il demande à geo.api.gouv.fr la commune qui contient la position de la ville ;
    2. avec le code INSEE, il demande à geo.api.gouv.fr le département et la région de la commune.
Il ne remplit que les colonnes vides : rien n'est réécrit, ni le nom, ni la position. Relancé, il ne refait rien.
Aucun agent n'est appelé : geo.api.gouv.fr est gratuit.

    python -m etl.fill_city_admin --essai     # montre ce qui serait écrit, n'écrit rien
    python -m etl.fill_city_admin
"""
import argparse
import json
import time

from utils.db_utils import MySQLUtils
from utils.geo_utils import get_commune_details, get_commune_from_coordinates
from utils.logger_util import LoggerUtil

logger = LoggerUtil.get_logger("fill_city_admin")

PAUSE_SECONDS = 0.2     # geo.api.gouv.fr limite le nombre de requêtes par seconde


def cities_to_fill(cursor) -> list:
    """Les villes à qui il manque la commune, le département, la région ou le pays."""
    cursor.execute("""
        SELECT id, name, latitude, longitude, commune, insee, department, region, country FROM cities
        WHERE insee IS NULL OR department IS NULL OR region IS NULL OR country IS NULL
        ORDER BY id
    """)
    return cursor.fetchall()


def find_admin(city: dict) -> dict | None:
    """
    Ce que geo.api.gouv.fr dit de la commune de cette ville : {commune, insee, department, region, country}.
    None si la ville est hors de France ou si l'API ne répond pas : la ville est alors laissée telle quelle.
    """
    commune, insee = city["commune"], city["insee"]
    if not insee:
        commune, insee = get_commune_from_coordinates(city["latitude"], city["longitude"])
        if not insee:
            return None
    details = get_commune_details(insee)
    if details is None:
        return None
    return {"commune": commune or details["name"], "insee": insee, "department": details["department"],
            "region": details["region"], "country": "France"}


def write_admin(cursor, city_id: int, admin: dict) -> None:
    """
    Écrit la commune et ses découpages, seulement dans les colonnes encore vides : COALESCE garde la valeur déjà
    en base quand il y en a une.
    """
    cursor.execute("""
        UPDATE cities SET commune = COALESCE(commune, %s), insee = COALESCE(insee, %s),
                          department = COALESCE(department, %s), region = COALESCE(region, %s),
                          country = COALESCE(country, %s)
        WHERE id = %s
    """, (admin["commune"], admin["insee"], admin["department"], admin["region"], admin["country"], city_id))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--essai", action="store_true", help="Montre ce qui serait écrit, n'écrit rien")
    args = parser.parse_args()
    counts = {"completees": 0, "sans_reponse": 0}
    # « with » : la connexion se ferme à la sortie du bloc, même en cas d'erreur (issue #206).
    with MySQLUtils.open_cursor(dictionary=True) as (connection, cursor):
        for city in cities_to_fill(cursor):
            time.sleep(PAUSE_SECONDS)
            admin = find_admin(city)
            print(json.dumps({"id": city["id"], "ville": city["name"], **(admin or {"reponse": None})}, ensure_ascii=False))
            if admin is None:
                counts["sans_reponse"] += 1
                continue
            counts["completees"] += 1
            if args.essai:
                continue
            write_admin(cursor, city["id"], admin)
            connection.commit()
            logger.info(f"[villes] {city['name']} (id {city['id']}) : {admin}")
    print(json.dumps({"essai": args.essai, **counts}, ensure_ascii=False))


if __name__ == "__main__":
    main()
