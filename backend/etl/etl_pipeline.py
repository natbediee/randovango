
import threading
from utils.db_utils import MySQLUtils
from etl.extract.scraper_p4n import run_p4n_scraper
from etl.transform.transform_p4n import transform_p4n
from etl.load.load_p4n import load_p4n_to_mysql
from etl.extract.api_wikidata import extract_wikidata
from etl.transform.transform_wikidata import transform_wikidata
from etl.load.load_poi import load_wikidata_poi
from utils.logger_util import LoggerUtil
from etl.load.load_gpx import load_gpx_data
from etl.extract.api_meteo import extract_weather_data
from etl.load.load_meteo import load_weather_data
from etl.extract.gpx import extract_all_gpx_files, remove_file, ALREADY_LOADED, LOAD_FAILED


logger = LoggerUtil.get_logger("etl_pipeline")

# Verrou pour empêcher plusieurs scrapings P4N en parallèle
scraping_lock = threading.Lock()

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

    # 3. Extraction P4N en dernier (lent - Selenium ~4min) si la ville n'est pas déjà présente dans histo_scrap
    def city_already_scraped(city_name):
        # « with » : la connexion se ferme à la sortie du bloc, même en cas d'erreur (issue #206).
        with MySQLUtils.open_cursor() as (conn, cursor):
            cursor.execute("SELECT COUNT(*) FROM histo_scrap hs JOIN cities c ON hs.city_id = c.id WHERE c.name = %s", (city_name,))
            count = cursor.fetchone()[0]
        return count > 0

    # Verrou uniquement pour le scraping P4N (Selenium) pour éviter les conflits
    with scraping_lock:
        if city_already_scraped(city):
            logger.info(f"[ETL-SC] Ville déjà présente dans histo_scrap : {city}. Extraction P4N sautée.")
        else:
            try:
                logger.info(f"[ETL-SC] Extraction P4N pour la ville : {city} (scraping en cours...)")
                df_p4n = run_p4n_scraper(city, is_headless=True, save_csv=False)
                if df_p4n is not None:
                    df_transformed = transform_p4n(df_p4n)
                    load_p4n_to_mysql(df_transformed, city)
                    logger.info(f"[ETL-SC] P4N chargé pour la ville : {city}")
                    # Transformation post-chargement : harmonisation des
                    # descriptions des spots qui viennent d'entrer (agents/).
                    # Volontairement non bloquant - un scraping réussi ne
                    # doit pas échouer parce que la clé d'API manque ou que le
                    # modèle est indisponible ; les spots restent affichables sans.
                    try:
                        from agents.harmonize_spots import run_sample
                        run_sample(only_new=True)
                    except Exception as harmonize_error:
                        logger.warning(f"[ETL-SC] Harmonisation IA ignorée : {harmonize_error}")
                    # Dates d'ouverture des fiches nouvelles ou modifiées : sans elles, le spot reste proposé.
                    try:
                        from agents.read_openings import run as read_openings
                        read_openings()
                    except Exception as opening_error:
                        logger.warning(f"[ETL-SC] Lecture des ouvertures ignorée : {opening_error}")
                    # Vérification des fiches que l'harmonisation a marquées à vérifier : un doute part en relecture.
                    try:
                        from agents.verify_spots import run as verify_spots
                        verify_spots(only_new=True)
                    except Exception as verify_error:
                        logger.warning(f"[ETL-SC] Vérification des spots ignorée : {verify_error}")
                else:
                    logger.warning(f"[ETL-SC] Scraping P4N a échoué pour la ville : {city}")
            except Exception as e:
                logger.error(f"[ETL-SC] Erreur lors de l'extraction/chargement P4N: {e}")

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


def run_free_chain(chain_key, city):
    """
    Fait passer une chaîne gratuite sur la ville, comme un passage d'origine « etl », et attend sa fin : la suivante
    a besoin de ce qu'elle a chargé. Le passage garde son échec en base ; ici, on l'écrit seulement dans le journal.
    """
    try:
        from services import passage_service, passage_store, service_store
        city_id = next((row["id"] for row in service_store.load_cities() if row["name"] == city), None)
        if city_id is None:
            logger.error(f"[ETL-BG] {chain_key} non lancée pour {city} : ville absente de la table cities")
            return
        passage_id = passage_service.create_passage(chain_key, city_id, origin="etl")
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
