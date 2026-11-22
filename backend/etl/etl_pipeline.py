
import threading
from utils.db_utils import MySQLUtils
from etl.extract.api_wikidata import extract_wikidata
from etl.transform.transform_wikidata import transform_wikidata
from etl.load.load_poi import load_wikidata_poi
from utils.logger_util import LoggerUtil
from etl.load.load_gpx import load_gpx_data
from etl.extract.api_meteo import extract_weather_data
from etl.load.load_meteo import load_weather_data
from etl.extract.gpx import extract_all_gpx_files, remove_file, ALREADY_LOADED, LOAD_FAILED


logger = LoggerUtil.get_logger("etl_pipeline")

def scraping_background(city):
    """Fonction de scraping à exécuter en arrière-plan (thread séparé)"""
    logger.info(f"[ETL-BG] Début du scraping en arrière-plan pour la ville: {city}")
    
    # 1. Les chaînes gratuites, dans l'ordre : OSM, puis les carburants, puis les pharmacies FINESS (après OSM : une
    # pharmacie FINESS au nom de société, « SELARL… », prend le nom de la pharmacie OSM voisine). Chacune est un
    # passage (issue #276) : son échec est gardé en base avec sa raison, et la supervision le relance. Non bloquant :
    # un échec n'arrête jamais les étapes suivantes.
    for chain_key in FREE_CHAINS:
        run_free_chain(chain_key, city)

    # 2. Extraction Wikidata (rapide - API)
    try:
        logger.info(f"[ETL-BG] Extraction Wikidata pour la ville : {city}")
        wikidata_json = extract_wikidata(city)
        logger.info("[ETL-BG] Transformation Wikidata...")
        df_wiki = transform_wikidata(wikidata_json=wikidata_json, city_name=city)
        logger.info("[ETL-BG] Chargement Wikidata...")
        load_wikidata_poi(df_wiki=df_wiki, city_name=city)
        logger.info(f"[ETL-BG] Wikidata chargé pour la ville : {city}")
        # Un lieu de Wikidata est souvent déjà venu d'OSM (Fort Montbarey, Tour Vauban) : la règle des doublons repasse.
        from services import poi_duplicates_service
        poi_duplicates_service.after_load(city)
    except Exception as e:
        logger.error(f"[ETL-BG] Erreur Wikidata: {e}")

    # 3. La chaîne des spots (issue #276) : la source des spots relue autour de la ville (lent : un navigateur, environ
    # 4 minutes), puis les agents sur les spots de la ville encore à faire (harmonisation, ouvertures, vérification).
    # Une ville déjà lue n'est pas relue par l'ETL : seuls ses spots encore à faire passent par les agents. Son échec
    # est gardé en base avec sa raison, et la supervision le reprend. Non bloquant, comme les autres étapes.
    run_spot_chain(city)

    # 4. Pépites de Vany : les lieux incontournables autour de la ville, cherchés une
    # fois pour toutes par l'agent (quelques minutes). En dernier : la position des
    # lieux trouvés est recalée sur les POI chargés plus haut, et les spots P4N,
    # plus attendus, ne patientent pas derrière. Non bloquant, comme l'harmonisation.
    try:
        from services.pepite_service import search_city_places
        search_city_places(city)
    except Exception as pepites_error:
        logger.warning(f"[ETL-SC] Pépites de Vany ignorées pour {city} : {pepites_error}")

    # 5. Les services cherchés par les agents (restaurants, commerces, supermarchés, laveries, issue #211). En tout
    # dernier : une grande ville est découpée en zones d'après ses spots, chargés plus haut. Le passage entre dans la
    # file des passages, qui le lance quand le verrou et le budget du jour le permettent : l'ETL n'attend pas sa fin.
    launch_services(city)

    logger.info(f"[ETL-SC] Scraping terminé pour la ville: {city}")


# Les chaînes gratuites de l'ajout d'une ville, dans l'ordre où elles passent (services/etl_chains.py).
FREE_CHAINS = ("osm", "carburants", "finess")


# Les parties d'agents de la chaîne des spots, pour une ville déjà lue (services/spot_chain.py).
AGENT_SPOT_PARTS = ["harmonisation", "ouvertures", "verification"]


def city_already_scraped(city_name):
    """La source des spots a-t-elle déjà été lue pour cette ville (une ligne dans histo_scrap) ?"""
    # « with » : la connexion se ferme à la sortie du bloc, même en cas d'erreur (issue #206).
    with MySQLUtils.open_cursor() as (conn, cursor):
        cursor.execute("SELECT COUNT(*) FROM histo_scrap hs JOIN cities c ON hs.city_id = c.id WHERE c.name = %s",
                       (city_name,))
        return cursor.fetchone()[0] > 0


def run_spot_chain(city):
    """
    Fait passer la chaîne des spots sur la ville : toutes ses parties pour une ville jamais lue, seulement les parties
    d'agents pour une ville déjà lue (une seconde rando au même endroit ne relit pas la source des spots).
    """
    try:
        parts = AGENT_SPOT_PARTS if city_already_scraped(city) else None
    except Exception as read_error:
        logger.warning(f"[ETL-SC] spots ignorés pour {city} : {read_error}")
        return
    run_etl_passage("spots", city, parts)


def run_free_chain(chain_key, city):
    """Fait passer une chaîne gratuite (OSM, carburants, FINESS) sur la ville, toutes ses parties."""
    run_etl_passage(chain_key, city)


def run_etl_passage(chain_key, city, parts=None):
    """
    Fait passer une chaîne sur la ville, comme un passage d'origine « etl », et attend sa fin : l'étape suivante a
    besoin de ce qu'elle a chargé. Sans `parts`, toutes les parties de la chaîne. Le passage garde son échec en base ;
    ici, on l'écrit seulement dans le journal. Si le verrou de la chaîne est pris (un autre passage tourne), le passage
    reste en file et la file le fera partir après.
    """
    try:
        from services import passage_service, passage_store, service_store
        city_id = next((row["id"] for row in service_store.load_cities() if row["name"] == city), None)
        if city_id is None:
            logger.error(f"[ETL-BG] {chain_key} non lancée pour {city} : ville absente de la table cities")
            return
        passage_id = passage_service.create_passage(chain_key, city_id, parts, origin="etl")
        passage_service.run_passage(passage_id)
        passage = passage_store.load_passage(passage_id)
        if passage["status"] == passage_store.FAILED:
            logger.error(f"[ETL-BG] {chain_key} en échec pour {city} : {passage['error']} (passage {passage_id})")
        else:
            logger.info(f"[ETL-BG] {chain_key} pour {city} : {passage['status']} (passage {passage_id})")
    except Exception as chain_error:
        logger.warning(f"[ETL-BG] {chain_key} ignorée pour {city} : {chain_error}")


def launch_services(city):
    """
    Demande le passage de la chaîne des services pour la commune de la ville, puis réveille la file des passages.
    Non bloquant, comme les autres étapes : une ville sans passage reste affichable, et l'admin peut le lancer.
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


def complete_city(city):
    """Pour la ville d'une rando qui vient d'entrer : la météo tout de suite, puis le reste en arrière-plan."""
    # 1. Extraction et chargement météo pour la ville (rapide)
    try:
        logger.info(f"[ETL] Extraction météo pour la ville: {city}")
        weather_data = extract_weather_data(city)
        if weather_data:
            load_weather_data(weather_data, city)
            logger.info(f"[ETL] Données météo chargées pour la ville: {city}")
        else:
            logger.warning(f"[ETL] Aucune donnée météo à charger pour la ville: {city}")
    except Exception as e:
        logger.error(f"[ETL] Erreur lors de l'extraction/chargement météo: {e}")

    # 2. Lancer le scraping en arrière-plan (non bloquant)
    logger.info(f"[ETL_SC] Lancement du scraping en arrière-plan pour la ville: {city}")
    threading.Thread(target=scraping_background, args=(city,), daemon=True).start()


def main(user_role="user") -> list:
    """
    Traite les fichiers GPX du dossier d'attente et rend, pour chacun, {"filename", "city", "reason"} :
    la ville de la rando chargée, ou le motif du refus. La route upload_gpx y retrouve le fichier envoyé.
    """
    verifie = 1 if user_role == "admin" else 0
    outcomes = []
    for gpx_file in extract_all_gpx_files():
        outcome = load_one_gpx(gpx_file, verifie)
        if outcome["reason"]:
            logger.info(f"[ETL] Fichier {outcome['filename']} non chargé : {outcome['reason']}")
        else:
            logger.info(f"[ETL] Ville extraite du GPX: {outcome['city']}")
            complete_city(outcome["city"])
        outcomes.append(outcome)

    logger.info(f"[ETL] Pipeline principal terminé : {outcomes}")
    return outcomes


if __name__ == "__main__":
    main()
