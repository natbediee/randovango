"""
L'ETL d'une rando envoyée : lire le fichier GPX, charger la rando, puis compléter sa ville.

COMPLÉTER LA VILLE, PAR LA FILE DES PASSAGES (issue #316)
La météo se charge tout de suite. Le reste (OSM et Wikidata, carburants, FINESS, spots, pépites, services) est demandé
à la file des passages (services/passage_queue.py), qui fait partir un passage à la fois. Avant, chaque rando lançait
ces chaînes dans un fil de fond à elle : 98 randos envoyées ensemble le 23 novembre 2026 avaient lancé 62 OSM dans la
même minute (OpenStreetMap a refusé l'application), cinq OSM pour l'Île-d'Yeu, et ≈ 70 recherches de pépites en
parallèle, parties avant que le budget du jour ait pu les arrêter.

UN ENVOI EN MASSE RÉPOND VITE (issue #328)
Le 25 novembre 2026, un envoi de 240 randos a tenu la requête 5 minutes, et l'API ne répondait plus à personne :
lecture des fichiers 52 s, chargement 35 s, météo 44 s, et surtout la demande des chaînes, 180 s (≈ 1 s par ville,
dont 0,8 s pour les services, qui relisent les fichiers des passages). Désormais :
- les fichiers se lisent six à la fois (extract/gpx.py), et la commune de départ arrive avec son département et sa
  région, en une seule demande à l'État : une ville nouvelle ne lui en fait plus une seconde ;
- la météo attend Open-Meteo six villes à la fois (HTTP_WORKERS) ;
- la météo est demandée une fois par ville, et non plus une fois par rando ;
- la demande des chaînes à la file part dans un fil à elle, après la réponse : la requête ne l'attend plus. Ce fil ne
  fait que remplir la file ; c'est toujours la file qui fait partir les passages, un à la fois.
"""
import threading
from concurrent.futures import ThreadPoolExecutor

from utils.logger_util import LoggerUtil
from etl.load.load_gpx import load_gpx_data
from etl.extract.api_meteo import extract_weather_data
from etl.load.load_meteo import load_weather_data
from etl.extract.gpx import extract_all_gpx_files, remove_file, ALREADY_LOADED, LOAD_FAILED


logger = LoggerUtil.get_logger("etl_pipeline")

# Les chaînes de l'ajout d'une ville, hors services. La file les fait passer dans son propre ordre (CHAIN_ORDER de
# passage_queue.py) : FINESS après OSM (une pharmacie au nom de société, « SELARL… », prend le nom de la pharmacie OSM
# voisine), les pépites après les spots (leur position est recalée sur les lieux chargés), les services en dernier.
CITY_CHAINS = ("osm", "carburants", "finess", "spots", "pepites")

# Combien de villes attendent leur météo (Open-Meteo) en même temps pendant un envoi.
HTTP_WORKERS = 6

# Un seul fil de demande des chaînes travaille à la fois, même si deux envois se suivent de près. La règle « une chaîne
# déjà demandée n'est pas redemandée » lit la table passages : deux fils qui liraient en même temps la même ville
# pourraient tous deux la croire pas encore demandée, et la demander deux fois.
_requests_lock = threading.Lock()


def request_city_chains(city):
    """
    Met dans la file des passages les chaînes de la ville qui restent à faire, puis la réveille : elle les fera partir
    une à une. L'ETL n'attend pas leur fin. Une chaîne déjà faite ou déjà demandée n'est pas redemandée.
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
    Charge en base un fichier GPX déjà lu (extract_all_gpx_files) et rend son résultat :
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
    Le travail du fil de demande : met en file les chaînes de chaque ville, l'une après l'autre (request_city_chains),
    sous le verrou qui empêche deux envois de demander en même temps. Une erreur sur une ville n'arrête pas les autres.
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
    Lance le fil qui demande les chaînes des villes à la file, et rend tout de suite, sans attendre sa fin : la réponse
    de l'envoi n'attend plus les ≈ 1 s par ville de la demande. Le fil s'arrête avec l'API (« daemon ») ; s'il est
    coupé en route, les villes pas encore demandées se relancent depuis la supervision.
    """
    worker = threading.Thread(target=request_chains_of_cities, args=(list(cities),),
                              name="demande-des-chaines", daemon=True)
    worker.start()
    return worker


def complete_cities(cities) -> threading.Thread:
    """
    Pour les villes des randos qui viennent d'entrer : la météo tout de suite, six villes à la fois, puis le reste
    demandé à la file par un fil à part, que la fonction rend sans l'attendre. Chaque ville n'y est qu'une fois, même
    quand plusieurs randos y partent.
    """
    with ThreadPoolExecutor(max_workers=HTTP_WORKERS) as pool:
        # list(...) attend que toutes les météos soient faites ; une erreur y est déjà notée par load_weather.
        list(pool.map(load_weather, cities))
    return start_chain_requests(cities)


def loaded_cities(outcomes) -> list:
    """Les villes des randos chargées, chacune une seule fois, dans l'ordre d'arrivée des randos."""
    # dict.fromkeys retire les doublons en gardant l'ordre : la première rando d'une ville la place dans la liste.
    return list(dict.fromkeys(outcome["city"] for outcome in outcomes if not outcome["reason"]))


def main(user_role="user") -> list:
    """
    Traite les fichiers GPX du dossier d'attente et rend, pour chacun, {"filename", "city", "reason"} :
    la ville de la rando chargée, ou le motif du refus. La route upload_gpx y retrouve le fichier envoyé.
    Seuls la lecture, le chargement et la météo sont attendus ; les chaînes des villes sont demandées après (#328).
    """
    verifie = 1 if user_role == "admin" else 0
    gpx_files = extract_all_gpx_files()
    outcomes = []
    # Le chargement reste un fichier après l'autre : deux randos d'une même ville nouvelle, chargées en même temps,
    # pourraient chacune ne pas trouver la ville et la créer deux fois.
    for gpx_file in gpx_files:
        outcome = load_one_gpx(gpx_file, verifie)
        if outcome["reason"]:
            logger.info(f"[ETL] Fichier {outcome['filename']} non chargé : {outcome['reason']}")
        else:
            logger.info(f"[ETL] Ville extraite du GPX: {outcome['city']}")
        outcomes.append(outcome)
    complete_cities(loaded_cities(outcomes))

    logger.info(f"[ETL] Pipeline principal terminé : {outcomes}")
    return outcomes


if __name__ == "__main__":
    main()
