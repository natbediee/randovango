"""
Le lancement de la chaîne des services (service_chain.py) : un passage par commune, pour toutes ses catégories.

UN PASSAGE, UN IDENTIFIANT
Toutes les catégories d'une commune (restaurants, commerces) passent l'une après l'autre sous le même identifiant, porté
par chaque appel d'agent jusque dans llm_calls et par chaque fichier JSON. On relit ainsi tout ce que la commune a coûté
et l'enchaînement de ses agents (services/llm_calls_service.passage_calls).
Les catégories passent dans l'ordre de CATEGORIES : la suivante trouve en base ce que la précédente vient d'enregistrer.

UN SEUL PASSAGE À LA FOIS
Avant de créer un service, l'enregistrement cherche s'il existe déjà (service_store.find_known). Deux lancements en même
temps sur deux communes voisines liraient chacun la base avant que l'autre ait écrit, et créeraient le même service deux
fois. Un verrou tenu par MySQL (single_passage) l'empêche : le second lancement s'arrête tout de suite, avec un message.

UTILISATION (dans le conteneur backend, depuis /usr/src/app) :
    python -m agents.find_services --ville Plougonvelin
    python -m agents.find_services --ville Plougonvelin --categorie restaurants
    python -m agents.find_services --ville Plougonvelin --essai      # rien en base, les fichiers seuls
"""
import argparse
import json
from contextlib import contextmanager

from agents import service_chain
from agents.find_commerces import COMMERCES
from agents.find_restaurants import RESTAURANTS
from agents.llm_config import model_of
from agents.llm_service import mesure_passage, new_passage_id
from services import service_store
from utils.db_utils import MySQLUtils
from utils.geo_utils import city_commune
from utils.logger_util import LoggerUtil

logger = LoggerUtil.get_logger("agent_services")

# Les catégories de la chaîne, dans l'ordre où elles passent sur une commune.
CATEGORIES = (RESTAURANTS, COMMERCES)


# Le nom du verrou de MySQL : un seul lancement de la chaîne à la fois, quel que soit le conteneur qui le lance.
LOCK_NAME = "randovango_passage_services"
_lock_connection = None     # la connexion qui tient le verrou dans ce programme, tant qu'un lancement est en cours


class PassageRunning(RuntimeError):
    """Un autre lancement de la chaîne des services est en cours."""


@contextmanager
def single_passage():
    """
    Tient le verrou « un seul passage à la fois » pendant le bloc, ou lève PassageRunning si un autre lancement le tient.
    Le verrou appartient à une connexion MySQL gardée ouverte (GET_LOCK) : il se libère à la fin du bloc, et tout seul si le
    programme s'arrête brutalement. Un bloc dans un bloc ne le reprend pas : main le tient pour toutes ses communes, et
    run_passage le retrouve déjà tenu.
    """
    global _lock_connection
    if _lock_connection is not None:
        # Déjà tenu par ce lancement. Une requête garde la connexion éveillée entre deux communes ; si elle a été coupée,
        # le verrou est perdu et l'erreur remonte au lieu de continuer sans lui.
        cursor = _lock_connection.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchone()
        cursor.close()
        yield
        return
    connection = MySQLUtils.connect()
    cursor = connection.cursor()
    try:
        cursor.execute("SELECT GET_LOCK(%s, 0)", (LOCK_NAME,))
        if cursor.fetchone()[0] != 1:
            raise PassageRunning("Un passage de la chaîne des services est déjà en cours : attendre sa fin avant d'en lancer un autre.")
        _lock_connection = connection
        try:
            yield
        finally:
            _lock_connection = None
            cursor.execute("SELECT RELEASE_LOCK(%s)", (LOCK_NAME,))
            cursor.fetchone()
    finally:
        cursor.close()
        MySQLUtils.disconnect(connection)


def run_passage(city: dict, categories: tuple = CATEGORIES, trial: bool = False) -> dict:
    """
    Un passage d'une commune : chaque catégorie est cherchée puis enregistrée, sous un seul identifiant. À l'essai, rien
    n'est écrit en base. Renvoie l'identifiant et, par catégorie, le bilan de l'enregistrement ou les lieux trouvés.
    Lève LLMUnavailable si un agent n'a pas pu répondre : les catégories déjà passées restent enregistrées.
    Lève PassageRunning si un autre lancement est en cours.
    """
    passage_id = new_passage_id()
    results = {"passage": passage_id}
    with single_passage(), mesure_passage(passage_id):
        logger.info(f"[services] {city['name']} : passage {passage_id}, {[category.key for category in categories]}")
        for category in categories:
            answer = service_chain.search_commune(category, city)
            if trial:
                results[category.key] = {"lieux": [row["nom"] for row in answer[category.key]]}
            else:
                results[category.key] = service_store.save_commune(category, city, answer, category.prompt_version,
                                                                   model_of(category.find_agent))
    return results


def main():
    by_key = {category.key: category for category in CATEGORIES}
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ville", required=True, action="append", help="Commune de la table cities (répétable)")
    parser.add_argument("--categorie", action="append", choices=list(by_key), help="Une catégorie seulement (répétable) ; toutes par défaut")
    parser.add_argument("--essai", action="store_true", help="N'écrit rien en base : les réponses restent dans les fichiers")
    args = parser.parse_args()
    categories = tuple(by_key[key] for key in args.categorie or by_key)
    searched = set()
    try:
        # Le verrou est tenu pour toutes les communes du lancement : un autre ne peut pas se glisser entre deux.
        with single_passage():
            for name in args.ville:
                city = service_store.load_city(name)
                if not city:
                    logger.error(f"[services] {name} : commune inconnue")
                    continue
                if city["name"] != name:
                    logger.info(f"[services] {name} : cherchée comme {city_commune(city)}, depuis la ville {city['name']}")
                # Une commune n'est cherchée qu'une fois : --ville Morgat --ville Le Fret ne paie qu'un passage de Crozon.
                if service_store.commune_key(city) in searched:
                    logger.info(f"[services] {name} : {city_commune(city)} déjà cherchée")
                    continue
                searched.add(service_store.commune_key(city))
                print(json.dumps({"ville": name, **run_passage(city, categories, args.essai)}, ensure_ascii=False))
    except PassageRunning as error:
        logger.error(f"[services] {error}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
