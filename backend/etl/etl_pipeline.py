"""
L'ETL d'une rando envoyée : lire le fichier GPX, charger la rando, puis compléter sa ville.

COMPLÉTER LA VILLE, PAR LA FILE DES PASSAGES (issue #316)
La météo se charge tout de suite. Le reste (OSM et Wikidata, carburants, FINESS, spots, pépites, services) est demandé
à la file des passages (services/passage_queue.py), où chaque étape fait partir une ville à la fois. Avant, chaque rando lançait
ces chaînes dans un fil de fond à elle : 98 randos envoyées ensemble le 23 novembre 2026 avaient lancé 62 OSM dans la
même minute (OpenStreetMap a refusé l'application), cinq OSM pour l'Île-d'Yeu, et ≈ 70 recherches de pépites en
parallèle, parties avant que le budget du jour ait pu les arrêter.

LE FRONT PASSE DEVANT L'ENVOI EN MASSE (issue #328)
Le 25 novembre 2026, un envoi de 240 randos a tenu sa requête 5 minutes : la route traitait tout le dossier d'attente
avant de répondre, et l'API ne répondait plus à personne. Choix de l'utilisatrice du 27 novembre : qu'un envoi en masse
prenne du temps n'est pas grave, mais une demande du front doit toujours passer devant. Désormais :
- le fichier envoyé par la page d'ajout est traité seul, tout de suite (process_upload) : lu, chargé, sa météo, puis la
  réponse ; il n'attend plus les fichiers du dossier d'attente ;
- les fichiers du dossier d'attente passent ensuite, un à un, dans un fil de fond (process_waiting_folder). Le front
  ne les attend jamais : entre deux fichiers du dossier, son fichier passe ;
- la demande des chaînes d'une ville à la file se fait à côté, sans retenir la réponse (≈ 1 s par ville le 25 novembre).
  Ces fils ne font que remplir la file ; c'est toujours la file qui fait partir les passages, étape par étape.
"""
import os
import threading

from utils.logger_util import LoggerUtil
from etl.load.load_gpx import load_gpx_data
from etl.extract.api_meteo import extract_weather_data
from etl.load.load_meteo import load_weather_data
from etl.extract import gpx
from etl.extract.gpx import read_gpx_file, remove_file, ALREADY_LOADED, LOAD_FAILED


logger = LoggerUtil.get_logger("etl_pipeline")

# Les chaînes de l'ajout d'une ville, hors services. Chaque étape de la file a sa propre file (passage_steps.py) et
# attend, pour cette ville seule, ce dont elle dépend : FINESS après OSM (une pharmacie au nom de société, « SELARL… »,
# prend le nom de la pharmacie OSM voisine), les pépites et les services après OSM (leurs lieux servent d'indices et de
# recalage), les agents des spots après la lecture de leur source.
CITY_CHAINS = ("osm", "carburants", "finess", "spots", "pepites")

# Un seul chargement en base à la fois, entre le fichier du front et ceux du dossier : deux randos d'une même ville
# nouvelle, chargées en même temps, pourraient chacune ne pas trouver la ville et la créer deux fois. Un chargement dure
# quelques centièmes de seconde : le front n'attend au plus que celui d'un fichier du dossier.
_load_lock = threading.Lock()

# Un seul fil vide le dossier d'attente à la fois : deux envois rapprochés ne lisent pas deux fois le même fichier.
_folder_lock = threading.Lock()

# Un seul fil de demande des chaînes travaille à la fois, même si deux envois se suivent de près. La règle « une chaîne
# déjà demandée n'est pas redemandée » lit la table passages : deux fils qui liraient en même temps la même ville
# pourraient tous deux la croire pas encore demandée, et la demander deux fois.
_requests_lock = threading.Lock()


def request_city_chains(city):
    """
    Met dans la file des passages les chaînes de la ville qui restent à faire, puis la réveille : chaque étape les
    fera partir à son tour. L'ETL n'attend pas leur fin. Une chaîne déjà faite ou déjà demandée n'est pas redemandée.
    """
    for chain_key in CITY_CHAINS:
        request_chain(chain_key, city)
    launch_services(city)
    try:
        from services import passage_queue
        passage_queue.wake()
    except Exception as wake_error:
        # La file regarde de toute façon toutes les minutes : un réveil manqué ne perd aucun passage.
        logger.warning(f"[ETL] File des passages non réveillée : {wake_error}")


def request_chain(chain_key, city):
    """
    Demande une chaîne pour la ville (passage_service.request_city_chain). Non bloquant : une erreur (base injoignable)
    est écrite dans le journal, et les autres chaînes de la ville sont quand même demandées.
    """
    try:
        from services import passage_service
        passage_id = passage_service.request_city_chain(chain_key, city)
        if passage_id:
            logger.info(f"[ETL] {chain_key} demandée pour {city} : passage {passage_id}")
    except Exception as request_error:
        logger.warning(f"[ETL] {chain_key} non demandée pour {city} : {request_error}")


def launch_services(city):
    """
    Demande le passage de la chaîne des services pour la commune de la ville (request_etl_passage, issue #211), puis
    réveille la file des passages. Non bloquant, comme les autres étapes : une ville sans passage reste affichable, et
    l'admin peut le lancer.
    """
    try:
        from services import passage_queue, passage_service
        passage_id = passage_service.request_etl_passage(city)
        if passage_id:
            logger.info(f"[ETL-SC] Passage des services demandé pour {city} : {passage_id}")
            passage_queue.wake()
    except Exception as services_error:
        logger.warning(f"[ETL-SC] Passage des services non demandé pour {city} : {services_error}")

def load_one_gpx(gpx_file, verifie) -> dict:
    """
    Charge en base un fichier GPX déjà lu (read_gpx_file) et rend son résultat :
    {"filename", "city", "reason"}, avec la ville si la rando est chargée, sinon le motif du refus (issue #266).
    """
    outcome = {"filename": gpx_file["filename"], "city": None, "reason": gpx_file["reason"]}
    if outcome["reason"]:
        return outcome
    try:
        outcome["city"] = load_gpx_data(gpx_file["data"], gpx_file["gpx_path"], verifie=verifie)
    except Exception as e:
        # Une erreur de base ne doit ni laisser le fichier dans le dossier d'attente, ni bloquer les autres fichiers.
        logger.error(f"[ETL] Erreur au chargement de {gpx_file['filename']} : {e}")
        remove_file(gpx_file["gpx_path"])
        outcome["reason"] = LOAD_FAILED
        return outcome
    if not outcome["city"]:
        # load_gpx_data ne rend pas de ville quand le tracé était déjà dans MongoDB.
        outcome["reason"] = ALREADY_LOADED
    return outcome


def load_weather(city) -> None:
    """Charge les prévisions météo d'une ville. Non bloquant : une erreur est notée, l'envoi continue."""
    try:
        logger.info(f"[ETL] Extraction météo pour la ville: {city}")
        weather_data = extract_weather_data(city)
        if weather_data:
            load_weather_data(weather_data, city)
            logger.info(f"[ETL] Données météo chargées pour la ville: {city}")
        else:
            logger.warning(f"[ETL] Aucune donnée météo à charger pour la ville: {city}")
    except Exception as e:
        logger.error(f"[ETL] Erreur lors de l'extraction/chargement météo pour {city} : {e}")


def request_chains_of_cities(cities) -> None:
    """
    Met en file les chaînes de chaque ville, l'une après l'autre (request_city_chains), sous le verrou qui empêche deux
    fils de demander en même temps. Une erreur sur une ville n'arrête pas les autres.
    """
    with _requests_lock:
        for city in cities:
            try:
                request_city_chains(city)
            except Exception as request_error:
                logger.warning(f"[ETL] Chaînes non demandées pour {city} : {request_error}")
        logger.info(f"[ETL] Chaînes demandées à la file pour {len(cities)} ville(s)")


def start_chain_requests(cities) -> threading.Thread:
    """
    Lance le fil qui demande les chaînes des villes à la file, et le rend tout de suite, sans attendre sa fin : la
    réponse au front n'attend pas les ≈ 1 s par ville de la demande. Le fil s'arrête avec l'API (« daemon ») ; s'il est
    coupé en route, une ville pas encore demandée se lance depuis la supervision.
    """
    worker = threading.Thread(target=request_chains_of_cities, args=(list(cities),),
                              name="demande-des-chaines", daemon=True)
    worker.start()
    return worker


def process_file(gpx_path, fname, verifie, allow_same_path=False) -> dict:
    """
    Lit un fichier GPX puis le charge en base, et rend son résultat {"filename", "city", "reason", "same_path"}.
    La lecture se fait sans verrou (elle attend surtout geo.api.gouv.fr) ; le chargement prend le verrou des
    chargements. allow_same_path : l'admin confirme un tracé qui suit le chemin d'une rando en base (issue #271).
    """
    gpx_file = read_gpx_file(gpx_path, fname, allow_same_path)
    with _load_lock:
        outcome = load_one_gpx(gpx_file, verifie)
    # La rando en base dont ce tracé suit le chemin, s'il est refusé pour cela : la route la rend à la page d'ajout.
    outcome["same_path"] = gpx_file.get("same_path")
    if outcome["reason"]:
        logger.info(f"[ETL] Fichier {fname} non chargé : {outcome['reason']}")
    else:
        logger.info(f"[ETL] Ville extraite du GPX: {outcome['city']}")
    return outcome


def process_upload(gpx_path, user_role="user", allow_same_path=False) -> dict:
    """
    Le fichier envoyé par la page d'ajout, traité avant tout le reste : lu, chargé, la météo de sa ville, puis son
    résultat rendu à la route. Les chaînes de sa ville sont demandées à côté. Les fichiers du dossier d'attente, s'il y
    en a, partent ensuite dans le fil de fond (start_folder_worker) : la réponse ne les attend pas.
    allow_same_path : l'admin confirme le chargement d'un tracé qui suit le chemin d'une rando en base (issue #271).
    Les fichiers du dossier d'attente, eux, n'ont personne pour confirmer : ils restent refusés dans ce cas.
    """
    verifie = 1 if user_role == "admin" else 0
    outcome = process_file(str(gpx_path), os.path.basename(gpx_path), verifie, allow_same_path)
    if not outcome["reason"]:
        load_weather(outcome["city"])
        start_chain_requests([outcome["city"]])
    start_folder_worker(user_role)
    return outcome


def process_waiting_folder(user_role="user") -> list:
    """
    Vide le dossier d'attente, un fichier après l'autre, et rend leurs résultats. Pour chaque ville vue pour la première
    fois dans ce passage : sa météo, puis ses chaînes demandées à la file. Un fichier déposé pendant le passage est pris
    aussi. Si un autre fil vide déjà le dossier, ne fait rien : il prendra ces fichiers.
    Chaque fichier n'est essayé qu'une fois par passage : un fichier qui resterait (erreur inattendue) ne fait pas
    tourner le fil sans fin.
    """
    if not _folder_lock.acquire(blocking=False):
        return []
    try:
        verifie = 1 if user_role == "admin" else 0
        outcomes, tried, cities_done = [], set(), set()
        while True:
            fnames = [fname for fname in gpx.waiting_files() if fname not in tried]
            if not fnames:
                break
            for fname in fnames:
                tried.add(fname)
                outcome = process_waiting_file(fname, verifie)
                outcomes.append(outcome)
                city = outcome["city"]
                if city and city not in cities_done:
                    cities_done.add(city)
                    load_weather(city)
                    request_chains_of_cities([city])
        logger.info(f"[ETL] Dossier d'attente vidé : {len(outcomes)} fichier(s), {len(cities_done)} ville(s)")
        return outcomes
    finally:
        _folder_lock.release()


def process_waiting_file(fname, verifie) -> dict:
    """Un fichier du dossier d'attente ; une erreur inattendue devient un refus, et le fil passe au suivant."""
    logger.info(f"[Extract] : Début du pipeline. Fichier GPX détecté: {fname}")
    try:
        return process_file(os.path.join(gpx.GPX_DIR, fname), fname, verifie)
    except Exception as error:
        logger.error(f"[ETL] Erreur sur {fname} : {error}")
        return {"filename": fname, "city": None, "reason": LOAD_FAILED}


def start_folder_worker(user_role="user") -> threading.Thread | None:
    """
    Lance le fil qui vide le dossier d'attente s'il y a des fichiers, et le rend sans l'attendre (None s'il n'y a rien
    à faire). S'il tourne déjà, le nouveau fil s'arrête aussitôt : celui qui tourne prend les fichiers nouveaux.
    """
    if not gpx.waiting_files():
        return None
    worker = threading.Thread(target=process_waiting_folder, args=(user_role,),
                              name="dossier-d-attente", daemon=True)
    worker.start()
    return worker


if __name__ == "__main__":
    # En ligne de commande : vide le dossier d'attente tout de suite, sans attendre un envoi.
    process_waiting_folder(user_role="admin")
