# Fichier : src/extraction/wikidata_extractor.py

import requests
import os
import json
import time 
import sys 
import logging

from pathlib import Path
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[3]
load_dotenv(ROOT / ".env")

# Création du dossier logs si nécessaire
log_folder = ROOT / "logs"
os.makedirs(log_folder, exist_ok=True)

# Configuration du logging
logging.basicConfig(
    level=logging.DEBUG,  # Niveau de log (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),  # Affiche les logs dans la console
        logging.FileHandler(log_folder / "api_wikidata.log", mode='a', encoding='utf-8')  # Sauvegarde dans un fichier log
    ]
)

# Réduction des logs pour les requêtes HTTP
logging.getLogger("urllib3").setLevel(logging.WARNING)

# Chemin vers data/in
DATA_IN = ROOT / os.getenv("DATA_IN") / "wikidata"

def fetch_wikidata_data(city):
    """
    Récupère les POI dans un rayon de 10 km autour de la ville, en utilisant des
    agrégations (GROUP BY) pour simplifier les données et obtenir tous les types
    (types) et labels (itemLabel) corrects en une seule ligne par POI.
    """
    logging.info(f"Lancement de l'extraction Wikidata pour : {city}")
    
    # --- Requête SPARQL ---
    sparql_query = f"""
        SELECT ?item
            (SAMPLE(?label) AS ?itemLabel)
            (SAMPLE(?desc) AS ?itemDescription)
            (SAMPLE(?coord) AS ?coord)
            (SAMPLE(?image) AS ?image)
            (SAMPLE(?commonsCat) AS ?commonsCat)
            (GROUP_CONCAT(DISTINCT ?baseTypeLabel; separator=", ") AS ?types)
        WHERE {{
          # 1. Centre = La commune de recherche
          BIND("{city}"@fr AS ?name)
          ?place rdfs:label ?name ;
                 wdt:P31/wdt:P279* wd:Q484170 ; # Commune de France
                 wdt:P625 ?center .

          # 2. POI dans un rayon de 10 km (recherche géographique)
          ?item wdt:P625 ?coord .
          SERVICE wikibase:around {{
            ?item wdt:P625 ?loc .
            bd:serviceParam wikibase:center ?center .
            bd:serviceParam wikibase:radius "10" .
          }}

          # 3. Types visés (incluant les sous-classes)
          VALUES ?baseType {{
            wd:Q570116  # Phare
            wd:Q23397   # Plage
            wd:Q57821   # Fort
            wd:Q16970   # Monument
            wd:Q839954  # Phare (répétition mais utile pour la robustesse)
            wd:Q4989906 # Site naturel / Géosite (ajouté pour la côte)
            wd:Q49899   # Église / Chapelle
            wd:Q44539   # Ruines
          }}
          ?item wdt:P31/wdt:P279* ?baseType .

          # 4. Propriétés Optionnelles
          OPTIONAL {{ ?item wdt:P18 ?image. }}
          OPTIONAL {{ ?item wdt:P373 ?commonsCat. }}
          OPTIONAL {{ ?item schema:description ?desc FILTER(LANG(?desc)="fr") }}

          # 5. Labels robustes avec fallback (pour éviter les valeurs vides)
          OPTIONAL {{ ?item rdfs:label ?lfr FILTER(LANG(?lfr)="fr") }}
          OPTIONAL {{ ?item rdfs:label ?len FILTER(LANG(?len)="en") }}
          BIND( COALESCE(?lfr, ?len, STRAFTER(STR(?item),"entity/")) AS ?label )

          # 6. Service de labels pour les types
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language "fr,en".
                                   ?baseType rdfs:label ?baseTypeLabel. }}
        }}
        GROUP BY ?item
        ORDER BY ?itemLabel
        LIMIT 500
    """
    
    wikidata_url = 'https://query.wikidata.org/sparql'
    params = {'query': sparql_query, 'format': 'json'} 
    headers = {'User-Agent': f'MonProjetGeospatial/{city} (contact@example.com)'}
    
    MAX_RETRIES = 3
    
    # --- Logique de réessai ---
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(wikidata_url, params=params, headers=headers)
            response.raise_for_status() 

            data = response.json()
            
            if not data.get('results', {}).get('bindings'):
                logging.warning(f"AVERTISSEMENT : La requête a réussi, mais 0 POI a été trouvé autour de {city}.")
                return 

            # --- Sauvegarde du JSON brut ---
            output_folder = DATA_IN
            os.makedirs(output_folder, exist_ok=True)
            
            filename = f'wikidata_data_{city.replace(" ", "_")}.json'
            file_path = os.path.join(output_folder, filename)
            
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
                
            logging.info(f"Données Wikidata sauvegardées : {file_path} ({len(data['results']['bindings'])} POI)")
            return file_path
            
        except requests.exceptions.HTTPError as e:
            if response.status_code == 504 and attempt < MAX_RETRIES - 1:
                logging.warning(f"Erreur 504, tentative de réessai dans 5 secondes ({attempt + 1}/{MAX_RETRIES})...")
                time.sleep(5)
                continue
            logging.error(f"Erreur HTTP {response.status_code}: {e}")
            raise Exception(f"Erreur HTTP {response.status_code}: {e}")
        
        except requests.exceptions.RequestException as e:
             raise Exception(f"Erreur de connexion : {e}")
        except Exception as e:
             raise Exception(f"Erreur de traitement des données : {e}")


# ----------------------------------------------------------------------
# BLOC DE LANCEMENT DIRECT (MAIN)
# ----------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Erreur: Veuillez spécifier le nom de la ville à rechercher.")
        print('Usage: python3 wikidata_extractor.py "Nom de la Ville"')
        sys.exit(1)

    city_raw = sys.argv[1]
    city_to_search = city_raw.title()  # Normalisation pour correspondre au Label Wikidata

    try:
        os.makedirs(os.path.join('data_input', 'raw'), exist_ok=True)

        print("\n=======================================================")
        print(f"Lancement de l'extraction Wikidata pour la ville: {city_to_search}")
        print("=======================================================")

        fetch_wikidata_data(city_to_search)
        print("\nExtraction Wikidata terminée.")

    except Exception as e:
        print("\nÉCHEC FATAL : L'extraction Wikidata n'a pas réussi.")
        print(f"Détail de l'erreur : {e}")