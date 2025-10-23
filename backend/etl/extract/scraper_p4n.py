import sys
import time
import os
import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.service import Service 
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, StaleElementReferenceException
from pathlib import Path
from dotenv import load_dotenv
import logging

from backend.utils.geo_utils import get_coordinates_for_city

ROOT = Path(__file__).resolve().parents[3]
load_dotenv(ROOT / ".env")

# Configuration du logging
logging.basicConfig(
    level=logging.DEBUG,  # Niveau de log (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),  # Affiche les logs dans la console
        logging.FileHandler(ROOT / "logs/scraper_p4n.log", mode='a', encoding='utf-8')  # Sauvegarde dans un fichier log
    ]
)

# Réduction des logs pour les requêtes HTTP et Selenium
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("selenium").setLevel(logging.WARNING)

# Réduction des logs pour webdriver_manager
logging.getLogger("webdriver_manager").setLevel(logging.WARNING)

# Nettoyage des handlers existants pour éviter les doublons
for handler in logging.root.handlers[:]:
    logging.root.removeHandler(handler)

# Reconfiguration du logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(ROOT / "logs/scraper_p4n.log", mode='a', encoding='utf-8')
    ]
)

# Chemin vers data/in
DATA_IN = ROOT / os.getenv("DATA_IN") / "p4n"

# --- CONFIGURATION FIXE ---
CHROME_BINARY_PATH = '/usr/bin/google-chrome' 
BASE_SEARCH_URL = "https://park4night.com/fr/search" 
ZOOM_LEVEL = 15 # Niveau de zoom par défaut pour un affichage local
# ---


# --- Fonction d'Extraction des Détails d'un Emplacement ---
def scrape_place_details(driver, url, wait):
    logging.info(f"--- Scraping de l'URL : {url} ---")
    try:
        driver.get(url)  
        header_name_element = wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'h1.place-header-name'))
        )
        name = header_name_element.text.strip()
        coords_text = "Coordonnées non trouvées"
        try:
             coords_element = driver.find_element(By.XPATH, "//span[contains(text(), '(lat, lng)')]")
             coords_text = coords_element.text.split('(')[0].strip()
        except NoSuchElementException:
             pass
        place_type_element = driver.find_element(By.CSS_SELECTOR, 'span.place-specs-type.tag')
        place_type = place_type_element.text.strip()
        rating_score = "Non trouvé / Non noté"
        try:
            # Ciblage du SPAN contenant la note exacte (2.17/5)
            rating_element = driver.find_element(
            By.CSS_SELECTOR, 
            'span.rating-note'
            )
            rating_score = rating_element.text.strip()
        except NoSuchElementException:
            pass # La valeur par défaut 'Non trouvé / Non noté' est conservée

        address_text = "Adresse non trouvée"
        try:
            # La liste UL a la classe 'place-info-location'
            # On cible le deuxième LI de cette liste, qui contient l'adresse
            address_li = driver.find_element(By.CSS_SELECTOR, 'ul.place-info-location li:nth-child(2)')
        
            # Le texte complet (Rue, Code Postal Ville, Pays) se trouve dans le <p> enfant
            address_p = address_li.find_element(By.TAG_NAME, 'p')
        
            # Le texte est récupéré, nettoyé des balises <br> par des virgules
            # et on enlève les espaces superflus (strip)
            address_text = address_p.get_attribute('innerText').replace('\n', ', ').strip()

        except NoSuchElementException:
            pass # Reste 'Adresse non trouvée sur la fiche'

        services = []
        try:
            service_elements = driver.find_elements(By.CSS_SELECTOR, 'ul.place-specs-services li img')
            for element in service_elements:
                service_name = element.get_attribute('aria-label')
                if service_name:
                    services.append(service_name)
        except NoSuchElementException:
            services.append("Aucun service listé")

        logging.info(f"Extrait: {name}")
        
        return {
            'URL_fiche': url,
            'Nom_Place': name,
            'Coordonnees': coords_text,
            'Adresse_Complete': address_text,
            'Type_Place': place_type,
            'Note_Avis': rating_score,
            'Services': ', '.join(services)
        }

    except (TimeoutException, NoSuchElementException, StaleElementReferenceException) as e:
        logging.error(f"Erreur lors du scraping de {url}: {type(e).__name__}")
        return {'URL_fiche': url, 'Erreur': f"Impossible de scraper les détails: {type(e).__name__}"}

# --- Fonction Principale de Scraping (MODIFIÉE) ---

def run_p4n_scraper(city_name, is_headless=True):
    """
    Obtient les coordonnées de la ville, construit l'URL de recherche Park4Night,
    scrappe les résultats et sauvegarde en CSV.
    """
    latitude, longitude = get_coordinates_for_city(city_name)
    
    if not latitude or not longitude:
        logging.error("Échec de la recherche : Impossible de continuer sans coordonnées.")
        return

    # 1. Construction de l'URL de recherche géographique
    search_url = f"{BASE_SEARCH_URL}?lat={latitude}&lng={longitude}&z={ZOOM_LEVEL}"
    logging.info(f" URL de recherche construite : {search_url}")

    driver = None
    scraped_data = []
    
    try:
        # Configuration des options du navigateur Chrome
        options = webdriver.ChromeOptions()
        options.add_argument('--no-sandbox') 
        options.add_argument('--disable-dev-shm-usage') 
        options.add_argument('--user-data-dir=/tmp/selenium_chrome_profile') 
        
        # NOTE : Commenté pour laisser ChromeDriverManager trouver le binaire.
        # options.binary_location = CHROME_BINARY_PATH 
        
        if is_headless:
            options.add_argument('--headless')
            logging.info(" Mode Headless activé (Sans interface graphique).")
        else:
            logging.info("Mode Visuel activé (Avec interface graphique, pour débogage).")

        service = Service(ChromeDriverManager().install())
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
            logging.info("Cookies gérés.")
        except Exception:
            pass
        
        # --- Récupération des Liens de Résultats (L'attente critique) ---
        RESULT_LIST_ID = "searchmap-list-results"
        # On attend la liste des résultats après que la carte ait chargé
        wait.until(EC.presence_of_element_located((By.ID, RESULT_LIST_ID)))
        
        links_elements = driver.find_elements(
            By.CSS_SELECTOR, 
            f'#{RESULT_LIST_ID} li a[href*="/fr/place/"]'
        )

        place_urls = []
        base_url = "https://park4night.com" 

        for link_element in links_elements:
            href = link_element.get_attribute('href')
            if href:
                place_urls.append(href if "http" in href else base_url + href)
        
        logging.info(f"\n {len(place_urls)} URLs de fiches d'emplacements trouvées.")
        
        # --- Scraping des Pages Détails (Le reste du processus) ---
        if not place_urls:
            logging.warning("Aucun lien trouvé.")
            return

        logging.info("\n--- Démarrage du Scraping des Fiches Détails ---")
        for url in place_urls:
            data = scrape_place_details(driver, url, wait)
            if 'Erreur' not in data:
                 scraped_data.append(data)
            
            time.sleep(1)
            
        # --- Sauvegarde CSV avec PANDAS ---
        if scraped_data:
            df = pd.DataFrame(scraped_data)
            # Ajout du check de DataFrame vide pour éviter l'écrasement
            if not df.empty:
                # 1. Définition du chemin de sauvegarde
                output_folder = DATA_IN 
                os.makedirs(output_folder, exist_ok=True) # Crée le dossier s'il n'existe pas
                
                csv_file_name = f'p4n_results_{city_name.replace(" ", "_")}.csv' 
                csv_file_path = os.path.join(output_folder, csv_file_name) # Chemin complet
                
                # 2. Sauvegarde au bon emplacement
                df.to_csv(csv_file_path, sep=';', index=False, encoding='utf-8')
                
                logging.info(f"\n SUCCÈS : {len(scraped_data)} emplacements sauvegardés dans '{csv_file_path}' avec Pandas.")
            else:
                 logging.warning(f"Aucune donnée trouvée pour {city_name}. Le fichier précédent n'a pas été créé/écrasé.")
        else:
            logging.warning("Aucune donnée valide à sauvegarder.")

    except TimeoutException:
        logging.error(" ÉCHEC : Timeout. La liste des résultats n'a pas chargé à temps.")
        sys.exit(1)
        
    except Exception as e:
        logging.critical(f" ERREUR FATALE : {e}")
        sys.exit(1) 

    finally:
        if driver:
            driver.quit()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: python3 scraper_p4n.py "Nom de la Ville" [--debug | --show]')
        sys.exit(1)

    city_to_scrape = sys.argv[1]

    # Mode par défaut : headless (sans interface)
    run_in_headless = True

    if len(sys.argv) > 2:
        option = sys.argv[2].lower()
        if option in ['--debug', '--show', 'debug', 'show']:
            run_in_headless = False
            print(f"Mode de débogage ({option}) détecté : le navigateur sera visible.")

    print("------------------------------------------------------")
    print(f"Lancement du scraping pour la ville : {city_to_scrape}")
    run_p4n_scraper(city_to_scrape, run_in_headless)
    print("Scraping terminé")
