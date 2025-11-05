import sys
import time
import os
import pandas as pd
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.service import Service 
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException, NoSuchElementException, StaleElementReferenceException
from utils.logger_util import LoggerUtil
from utils.service_utils import ServiceUtil

from utils.geo_utils import get_coordinates_for_city
from utils.db_utils import p4n_id_exists


ServiceUtil.load_env()

logger = LoggerUtil.get_logger("etl_p4n")

# Chemin vers data à la racine du projet (volume Docker)
DATA = Path(__file__).resolve().parents[2] / "data"

# --- CONFIGURATION FIXE ---
CHROME_BINARY_PATH = '/usr/bin/chromium'  # Pour Docker : Chromium Debian
CHROMEDRIVER_PATH = '/usr/bin/chromedriver'      # Pour Docker : chromedriver Debian
BASE_SEARCH_URL = "https://park4night.com/fr/search" 
ZOOM_LEVEL = 15 # Niveau de zoom par défaut pour un affichage local
# ---


# --- Fonction d'Extraction des Détails d'un Emplacement ---
def scrape_place_details(driver, url, wait) -> dict:
    logger.info(f"[Extract] : Scraping de l'URL : {url} ---")
    try:
        driver.get(url)
        # --- Extraction du nom du lieu ---
        header_name_element = wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'h1.place-header-name'))
        )
        name = header_name_element.text.strip()

        # --- Extraction des coordonnées ---
        coords_text = "Coordonnées non trouvées"
        try:
            coords_element = driver.find_element(By.XPATH, "//span[contains(text(), '(lat, lng)')]")
            coords_text = coords_element.text.split('(')[0].strip()
        except NoSuchElementException:
            pass

        # --- Extraction du type de lieu ---
        place_type_element = driver.find_element(By.CSS_SELECTOR, 'span.place-specs-type.tag')
        place_type = place_type_element.text.strip()

        # --- Extraction de la note ---
        rating_score = None
        try:
            rating_element = driver.find_element(By.CSS_SELECTOR, 'span.rating-note')
            rating_score = rating_element.text.strip()
        except NoSuchElementException:
            pass

        # --- Extraction de la description (fr) ---
        description_text = "Description non trouvée"
        try:
            desc_div = driver.find_element(By.CSS_SELECTOR, 'div.place-info-description.mt-4')
            desc_p = desc_div.find_element(By.CSS_SELECTOR, 'p[lang="fr"]')
            description_text = desc_p.text.strip()
        except NoSuchElementException:
            pass

        # --- Extraction des services disponibles ---
        services = []
        try:
            service_elements = driver.find_elements(By.CSS_SELECTOR, 'ul.place-specs-services li img')
            for element in service_elements:
                service_name = element.get_attribute('aria-label')
                if service_name:
                    services.append(service_name)
        except NoSuchElementException:
            services.append("Aucun service listé")
        logger.info(f"[Extract] : Extrait: {name}")
        result = {
            'URL_fiche': url,
            'Nom_Place': name,
            'Coordonnees': coords_text,
            'Description': description_text,
            'Type_Place': place_type,
            'Note_Avis': rating_score,
            'Services': ', '.join(services)
        }
        logger.debug(f"[Extract] : Sortie scrape_place_details: type={type(result)}, keys={list(result.keys())}")
        return result
    except (TimeoutException, NoSuchElementException, StaleElementReferenceException) as e:
        logger.error(f"[Extract] : Erreur lors du scraping de {url}: {type(e).__name__}")
        return {'URL_fiche': url, 'Erreur': f"Impossible de scraper les détails: {type(e).__name__}"}

# --- Fonction Principale de Scraping (MODIFIÉE) ---

def run_p4n_scraper(city_name : str, is_headless=True, save_csv=False) -> pd.DataFrame | None:
    """
    Obtient les coordonnées de la ville, construit l'URL de recherche Park4Night,
    scrappe les résultats et sauvegarde en CSV en option.
    """
    latitude, longitude = get_coordinates_for_city(city_name)
    
    if not latitude or not longitude:
        logger.error("[Extract] : Échec de la recherche : Impossible de continuer sans coordonnées.")
        return

    # 1. Construction de l'URL de recherche géographique
    search_url = f"{BASE_SEARCH_URL}?lat={latitude}&lng={longitude}&z={ZOOM_LEVEL}"
    logger.info(f"[Extract] : URL de recherche construite : {search_url}")

    driver = None
    scraped_data = []
    try:
        # Configuration des options du navigateur Chrome/Chromium
        options = webdriver.ChromeOptions()
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--user-data-dir=/tmp/selenium_chrome_profile')
        options.binary_location = CHROME_BINARY_PATH

        if is_headless:
            options.add_argument('--headless')
            logger.info("[Extract] : Mode Headless activé (Sans interface graphique).")
        else:
            logger.info("[Extract] : Mode Visuel activé (Avec interface graphique, pour débogage).")

        # Utilise le chromedriver installé dans le conteneur Docker
        service = Service(CHROMEDRIVER_PATH)
        driver = webdriver.Chrome(service=service, options=options)

        # 2. Accès direct à la page de résultats
        driver.get(search_url)
        wait = WebDriverWait(driver, 40) # 40s pour le chargement initial

        # --- Gestion des Cookies (Reste essentielle) ---
        try:
            consent_button = wait.until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, '.cc-container .cc-btn-reject'))
            )
            driver.execute_script("arguments[0].click();", consent_button)
            wait.until(EC.invisibility_of_element_located((By.CSS_SELECTOR, '.cc-container')))
            logger.info("[Extract] : Cookies gérés.")
        except Exception:
            pass

        # --- Récupération des Liens de Résultats (ancienne logique robuste) ---
        RESULT_LIST_ID = "searchmap-list-results"
        wait.until(EC.presence_of_element_located((By.ID, RESULT_LIST_ID)))
        links_elements = driver.find_elements(
            By.CSS_SELECTOR,
            f'#{RESULT_LIST_ID} li a[href*="/fr/place/"]'
        )
        base_url = "https://park4night.com"
        n_total = 0
        n_skipped = 0
        n_scraped = 0
        place_urls = []
        for link_element in links_elements:
            href = link_element.get_attribute('href')
            if href:
                url = href if "http" in href else base_url + href
                place_urls.append(url)
        if not place_urls:
            html_path = f"/usr/src/logs/p4n_debug_{city_name.replace(' ', '_')}.html"
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(driver.page_source)
            logger.warning(f"[Extract] : Aucun spot trouvé pour {city_name}. HTML sauvegardé dans {html_path}")
        for url in place_urls:
            n_total += 1
            # Extraire p4n_id depuis l'URL (ex: /fr/place/18293)
            try:
                p4n_id = url.split("/fr/place/")[1].split("/")[0]
            except Exception:
                p4n_id = None
            if p4n_id and p4n_id_exists(p4n_id):
                logger.info(f"[Extract] : Spot déjà en base (p4n_id={p4n_id}), on saute le scraping.")
                n_skipped += 1
                continue
            data = scrape_place_details(driver, url, wait)
            if 'Erreur' not in data:
                data['city'] = city_name
                data['p4n_id'] = p4n_id
                scraped_data.append(data)
                n_scraped += 1
            time.sleep(1)
        logger.info(f"[Extract] : {n_total} spots trouvés, {n_skipped} déjà en base, {n_scraped} nouveaux scrapés.")

        # --- Option de sauvegarde CSV manuelle ---
        if scraped_data:
            df = pd.DataFrame(scraped_data)
            if save_csv:
                if not df.empty:
                    output_folder = DATA
                    os.makedirs(output_folder, exist_ok=True)
                    csv_file_name = f'p4n_results_{city_name.replace(" ", "_")}.csv'
                    csv_file_path = os.path.join(output_folder, csv_file_name)
                    df.to_csv(csv_file_path, sep=';', index=False, encoding='utf-8')
                    logger.info(f"[Extract] : SUCCÈS : {len(scraped_data)} emplacements sauvegardés dans '{csv_file_path}' avec Pandas.")
                else:
                    logger.warning(f"[Extract] : Aucune donnée trouvée pour {city_name}. Le fichier précédent n'a pas été créé/écrasé.")
            # df peut être passé à transform et load
            logger.info(f"[Extract] : Sortie run_p4n_scraper: type=DataFrame, shape={df.shape}")
            return df
        else:
            logger.warning("[Extract] : Aucune donnée valide à traiter.")
            return None

    except TimeoutException:
        logger.error("[Extract] : ÉCHEC : Timeout. La liste des résultats n'a pas chargé à temps.")
        sys.exit(1)
    except Exception as e:
        logger.critical(f"[Extract] : ERREUR FATALE : {e}")
        sys.exit(1)
    finally:
        if driver:
            driver.quit()
