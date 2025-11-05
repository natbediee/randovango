import requests
import time 

from utils.logger_util import LoggerUtil

logger = LoggerUtil.get_logger("etl_wikidata")

def extract_wikidata(city) -> dict:
    """
    Récupère les POI dans un rayon de 5 km autour de la ville, en utilisant des
    agrégations (GROUP BY) pour simplifier les données et obtenir tous les types
    (types) et labels (itemLabel) corrects en une seule ligne par POI.
    """
    logger.info(f"[Extract] : Lancement de l'extraction Wikidata pour : {city}")
    
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

          # 2. POI dans un rayon de 5 km (recherche géographique)
          ?item wdt:P625 ?coord .
          SERVICE wikibase:around {{
            ?item wdt:P625 ?loc .
            bd:serviceParam wikibase:center ?center .
            bd:serviceParam wikibase:radius "5" .
          }}

          # 3. Types visés (incluant les sous-classes)
          VALUES ?baseType {{
            wd:Q570116  # Phare
            wd:Q23397   # Plage
            wd:Q57821   # Fort
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
                logger.warning(f"[Extract] : La requête a réussi, mais 0 POI a été trouvé autour de {city}.")
                return None
            logger.info(f"[Extract] : Données Wikidata extraites pour {city} ({len(data['results']['bindings'])} POI)")
            return data
            
        except requests.exceptions.HTTPError as e:
            if response.status_code == 504 and attempt < MAX_RETRIES - 1:
                logger.warning(f"[Extract] : Erreur 504, tentative de réessai dans 5 secondes ({attempt + 1}/{MAX_RETRIES})...")
                time.sleep(5)
                continue
            logger.error(f"[Extract] : Erreur HTTP {response.status_code}: {e}")
            raise Exception(f"[Extract] : Erreur HTTP {response.status_code}: {e}")

        except requests.exceptions.RequestException as e:
            raise Exception(f"[Extract] : Erreur de connexion : {e}")
        except Exception as e:
            raise Exception(f"[Extract] : Erreur de traitement des données : {e}")
