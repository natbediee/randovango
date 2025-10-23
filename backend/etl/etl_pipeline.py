import sys
import logging
import os
from pathlib import Path
from backend.utils.path_utils import add_etl_paths
from backend.etl.load.load_gpx import load_gpx
from backend.etl.extract.api_meteo import fetch_weather_data
from backend.utils.service_util import ServiceUtil
# À compléter avec les autres modules d'extraction
# from backend.etl.extract.api_osm import extract_osm
# from backend.etl.extract.api_wikidata import extract_wikidata
# from backend.etl.extract.scraper_p4n import extract_p4n

ROOT = Path(__file__).resolve().parents[2]
add_etl_paths(ROOT)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)

def main():
    # Récupère le dossier GPX depuis les variables d'environnement
    ServiceUtil.load_env()
    gpx_dir = ServiceUtil.get_env('DATA_GPX', 'data/in/gpx')
    
    # Trouve le premier fichier GPX dans le dossier
    gpx_files = [f for f in os.listdir(gpx_dir) if f.endswith('.gpx')]
    if not gpx_files:
        logging.error(f"[ETL] Aucun fichier GPX trouvé dans {gpx_dir}")
        sys.exit(1)
    
    gpx_file = os.path.join(gpx_dir, gpx_files[0])
    logging.info(f"[ETL] Import GPX: {gpx_file}")
    
    # 1. Import GPX (Mongo + MySQL) et récupération de la ville
    city = load_gpx()
    
    # Si le fichier existe déjà ou aucun fichier trouvé, arrêter le pipeline
    if city is None:
        logging.info("[ETL] Aucun nouveau fichier à traiter.")
        return
    
    # 2. Extraction météo pour la ville
    logging.info(f"[ETL] Extraction météo pour la ville: {city}")
    fetch_weather_data(city)
    # 3. Extraction OSM, Wiki, P4N (à compléter)
    # extract_osm(city)
    # extract_wikidata(city)
    # extract_p4n(city)
    logging.info("[ETL] Pipeline terminé.")

if __name__ == "__main__":
    main()
