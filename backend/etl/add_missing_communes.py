"""
Une ligne par commune dans cities, et les services et spots des lieux-dits repris par leur commune (issue #184).

POURQUOI
Une ville de l'appli vient du départ d'une rando : parfois un lieu-dit, pas une commune. Lilia et Tremenac'h sont en
Plouguerneau, Lochrist au Conquet. 22 villes sur 136 sont des lieux-dits, et 11 de leurs communes n'avaient aucune
ligne à leur nom : la station Carrefour Contact de Plouguerneau était introuvable en cherchant Plouguerneau.
Décision du 15 novembre 2026 : « Où pars-tu » ne propose plus que des communes. Les lignes des lieux-dits restent en
base, puisque d'anciens voyages et des randos les désignent, mais ne sont plus proposées.

CE QUE FAIT LE SCRIPT
    1. Pour chaque commune d'un lieu-dit qui n'a pas de ligne à son nom, il crée cette ligne : nom officiel, centre,
       département et région d'après geo.api.gouv.fr (gratuit, officiel), puis sa météo.
    2. Chaque service (histo_poi) et chaque spot (histo_scrap) lié à un lieu-dit est lié aussi à sa commune.
Il ne fait qu'ajouter : aucun lien n'est retiré, aucune ville renommée ni supprimée. Relancé, il ne refait rien.

    python -m etl.add_missing_communes --essai     # compte ce qui serait créé et repris, n'écrit rien
    python -m etl.add_missing_communes
"""
import argparse
import json

from etl.etl_meteo import run_meteo_etl
from utils.db_utils import MySQLUtils
from utils.geo_utils import get_commune_details
from utils.logger_util import LoggerUtil

logger = LoggerUtil.get_logger("add_missing_communes")

# Les tables de liens à reprendre, et la colonne qui y désigne le service ou le spot.
LINKS = {"histo_poi": "poi_id", "histo_scrap": "spot_id"}


def load_localities(cursor) -> list:
    """
    Les lieux-dits : les villes dont le nom n'est pas celui de leur commune. La comparaison de MySQL ignore la casse
    et les accents : « Plounéour-Brignogan-Plages » est bien sa commune, écrite « -plages ». « Penmarc'h », lui,
    est un lieu-dit de la commune officielle « Penmarch » : l'apostrophe compte.
    """
    cursor.execute("SELECT id, name, commune, insee FROM cities WHERE insee IS NOT NULL AND name <> commune ORDER BY id")
    return cursor.fetchall()


def load_commune_ids(cursor) -> dict:
    """{code INSEE : id} des lignes qui portent le nom de leur commune (Le Conquet, Crozon...)."""
    cursor.execute("SELECT insee, MIN(id) AS id FROM cities WHERE insee IS NOT NULL AND name = commune GROUP BY insee")
    return {row["insee"]: row["id"] for row in cursor.fetchall()}


def missing_communes(localities: list, commune_ids: dict) -> list:
    """Les codes INSEE des communes de lieux-dits qui n'ont pas de ligne à leur nom, sans doublon, dans l'ordre."""
    return sorted({locality["insee"] for locality in localities if locality["insee"] not in commune_ids})


def create_commune(cursor, details: dict) -> int:
    """Crée la ligne de la commune dans cities et renvoie son id."""
    cursor.execute("""
        INSERT INTO cities (name, latitude, longitude, department, region, country, commune, insee)
        VALUES (%s, %s, %s, %s, %s, 'France', %s, %s)
    """, (details["name"], details["latitude"], details["longitude"], details["department"], details["region"],
          details["name"], details["insee"]))
    return cursor.lastrowid


def count_new_links(cursor, table: str, locality_id: int, commune_id: int | None) -> int:
    """Combien de liens du lieu-dit la commune n'a pas encore (tous, si la commune n'a pas encore de ligne)."""
    column = LINKS[table]
    cursor.execute(f"""
        SELECT COUNT(*) AS n FROM {table} l
        WHERE l.city_id = %s
          AND NOT EXISTS (SELECT 1 FROM {table} o WHERE o.{column} = l.{column} AND o.city_id = %s)
    """, (locality_id, commune_id or 0))
    return cursor.fetchone()["n"]


def copy_links(cursor, table: str, locality_id: int, commune_id: int) -> None:
    """
    Lie à la commune tout ce qui est lié au lieu-dit. INSERT IGNORE : un lien que la commune a déjà (la clé unique
    service + ville) est laissé tel quel, et le script peut être relancé.
    """
    column = LINKS[table]
    cursor.execute(f"""
        INSERT IGNORE INTO {table} ({column}, city_id)
        SELECT {column}, %s FROM {table} WHERE city_id = %s
    """, (commune_id, locality_id))


def add_communes(connection, cursor, trial: bool) -> dict:
    """Crée les communes manquantes (étape 1 du script) et renvoie {code INSEE : id}, None pour une commune à l'essai."""
    localities, commune_ids = load_localities(cursor), load_commune_ids(cursor)
    for insee in missing_communes(localities, commune_ids):
        details = get_commune_details(insee)
        if details is None:
            logger.warning(f"[communes] {insee} : geo.api.gouv.fr sans réponse, commune non créée")
            continue
        print(json.dumps({"commune créée": details["name"], **details}, ensure_ascii=False))
        if trial:
            commune_ids[insee] = None
            continue
        commune_ids[insee] = create_commune(cursor, details)
        connection.commit()
        run_meteo_etl(details["name"], details["latitude"], details["longitude"])
    return commune_ids


def take_over_links(connection, cursor, commune_ids: dict, trial: bool) -> None:
    """Lie à leur commune les services et spots de chaque lieu-dit (étape 2 du script)."""
    for locality in load_localities(cursor):
        if locality["insee"] not in commune_ids:
            continue  # la commune n'a pas pu être créée
        commune_id = commune_ids[locality["insee"]]
        counts = {table: count_new_links(cursor, table, locality["id"], commune_id) for table in LINKS}
        print(json.dumps({"lieu-dit": locality["name"], "commune": locality["commune"], "services": counts["histo_poi"],
                          "spots": counts["histo_scrap"]}, ensure_ascii=False))
        if trial:
            continue
        for table in LINKS:
            copy_links(cursor, table, locality["id"], commune_id)
        connection.commit()
        logger.info(f"[communes] {locality['name']} repris par {locality['commune']} : {counts}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--essai", action="store_true", help="Compte ce qui serait créé et repris, n'écrit rien")
    args = parser.parse_args()
    # « with » : la connexion se ferme à la sortie du bloc, même en cas d'erreur (issue #206).
    with MySQLUtils.open_cursor(dictionary=True) as (connection, cursor):
        commune_ids = add_communes(connection, cursor, args.essai)
        take_over_links(connection, cursor, commune_ids, args.essai)


if __name__ == "__main__":
    main()
