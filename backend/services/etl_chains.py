"""
Les chaînes gratuites de l'ajout d'une ville : OSM (suivi de Wikidata, issue #316), pharmacies FINESS, carburants
(issue #276).

Elles se lancent et se suivent comme la chaîne des services (services/passage_service.py) : un passage par ville, une
trace en base, la raison d'un échec, la reprise depuis la supervision. Ce fichier donne, pour chacune, la fonction qui
fait passer sa seule partie, et le verrou qui empêche de lancer deux fois la même chaîne sur la même ville.

POURQUOI UN VERROU PAR VILLE
La chaîne des services n'a qu'un passage à la fois, toutes villes confondues : ses agents coûtent, et une grande ville
dure des heures. Les chaînes gratuites durent quelques secondes et ne coûtent rien : deux villes ajoutées coup sur coup
gardent leur OSM en même temps. Seule la même chaîne sur la même ville attend l'autre, pour ne pas écrire deux fois.

GRATUITES
Elles lisent des sources ouvertes (OpenStreetMap, fichiers de l'État) : le budget des agents ne les retient jamais.
"""
from contextlib import contextmanager

from agents.find_services import PassageRunning
from etl.etl_carburants import run_city_etl as run_fuel_etl
from etl.etl_osm import run_osm_etl
from etl.etl_pharmacies import run_new_city_etl as run_pharmacy_etl
from etl.etl_wikidata import run_wikidata_etl
from utils.db_utils import MySQLUtils


class StepFailed(RuntimeError):
    """Une étape gratuite n'a rien pu charger. Le message est la raison que lit l'administratrice."""


# --- Le verrou d'une chaîne sur une ville ---

def lock_name(chain_key: str, city_id: int) -> str:
    """Le nom du verrou de MySQL pour cette chaîne et cette ville, par exemple « randovango_osm_12 »."""
    return f"randovango_{chain_key}_{city_id}"


@contextmanager
def named_lock(name: str, busy_message: str):
    """
    Tient le verrou de MySQL de ce nom pendant le bloc, ou lève PassageRunning (avec `busy_message`) s'il est déjà tenu.
    Comme celui des services, le verrou appartient à une connexion MySQL (GET_LOCK) : il se libère à la fin du bloc, et
    tout seul si le serveur s'arrête en route. PassageRunning laisse le passage en file : la file le relancera.
    """
    connection = MySQLUtils.connect()
    cursor = connection.cursor()
    try:
        cursor.execute("SELECT GET_LOCK(%s, 0)", (name,))
        if cursor.fetchone()[0] != 1:
            raise PassageRunning(busy_message)
        try:
            yield
        finally:
            cursor.execute("SELECT RELEASE_LOCK(%s)", (name,))
            cursor.fetchone()
    finally:
        cursor.close()
        MySQLUtils.disconnect(connection)


def named_lock_is_free(name: str) -> bool:
    """Le verrou de MySQL de ce nom est-il libre ? Demandé sans le prendre (IS_FREE_LOCK)."""
    connection = MySQLUtils.connect()
    cursor = connection.cursor()
    try:
        cursor.execute("SELECT IS_FREE_LOCK(%s)", (name,))
        return cursor.fetchone()[0] == 1
    finally:
        cursor.close()
        MySQLUtils.disconnect(connection)


def city_lock(chain_key: str, city_id: int):
    """Le verrou de la chaîne sur la ville : un bloc « with », qui lève PassageRunning s'il est déjà tenu."""
    return named_lock(lock_name(chain_key, city_id), f"La chaîne {chain_key} tourne déjà sur cette ville : attendre sa fin.")


def city_lock_is_free(chain_key: str, city_id: int) -> bool:
    """Le verrou de la chaîne sur la ville est-il libre ?"""
    return named_lock_is_free(lock_name(chain_key, city_id))


# --- Les parties : une par chaîne ---
# Chacune a la forme attendue par passage_service.Chain.run_part : (passage, partie, ville, reprise, budget) -> bilan.
# La reprise et le budget ne servent pas : une chaîne gratuite se refait en entier, en quelques secondes.

def run_osm(passage_id: str, key: str, city: dict, resume: bool, check_budget) -> dict:
    """
    Les lieux d'OpenStreetMap autour de la ville (commerces, services, toilettes...), puis ceux de Wikidata (forts,
    phares...) ; leur nombre en bilan. Wikidata passe ici depuis l'issue #316, juste après OSM comme avant : la règle
    des doublons a besoin des deux. Son échec est seulement noté dans le journal : il ne fait pas échouer OSM, et le
    bilan ne donne alors que les lieux d'OSM.
    """
    count = run_osm_etl(city["name"])
    if count is None:
        raise StepFailed("OpenStreetMap n'a pas répondu (Overpass muet ou en erreur) : relancer plus tard")
    summary = {"lieux": count}
    wikidata_count = run_wikidata_etl(city["name"])
    if wikidata_count is not None:
        summary["lieux_wikidata"] = wikidata_count
    return summary


def run_finess(passage_id: str, key: str, city: dict, resume: bool, check_budget) -> dict:
    """Les pharmacies du registre FINESS autour de la ville, après OSM (leurs noms) ; leur nombre en bilan."""
    count = run_pharmacy_etl(city["name"])
    if count is None:
        raise StepFailed("fichier FINESS illisible ou ville sans position : relancer plus tard")
    return {"pharmacies": count}


def run_fuel(passage_id: str, key: str, city: dict, resume: bool, check_budget) -> dict:
    """Les stations-service et leurs prix (fichier de l'État, noms d'OSM) ; leur nombre en bilan."""
    count = run_fuel_etl(city["name"])
    if count is None:
        # Les noms et marques viennent des stations OSM rangées par la chaîne « osm » : sans elle, rien n'est chargé.
        raise StepFailed("fichier des prix des carburants illisible, étape OSM pas encore passée pour la ville, "
                         "ou ville sans position : relancer plus tard")
    return {"stations": count}
