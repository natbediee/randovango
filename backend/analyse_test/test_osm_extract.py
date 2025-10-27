import json
from etl.extract.api_osm import extract_osm
from etl.transform.transform_osm import transform_osm
from etl.load.load_poi import load_osm_poi

CITY = "Plougonvelin"

def main():
    print(f"Extraction OSM pour la ville : {CITY}")
    osm_json = extract_osm(CITY)
    # Sauvegarde du JSON extrait
    with open("data/in/osm_extract_plougonvelin.json", "w", encoding="utf-8") as f:
        json.dump(osm_json, f, ensure_ascii=False, indent=2)
    print(f"Données OSM brutes : {json.dumps(osm_json)[:500]} ...\n")
    df_osm = transform_osm(osm_json, city=CITY)
    print(f"DataFrame OSM transformé :\n{df_osm.head()}\n")
    load_osm_poi(df_osm, CITY)
    print("Chargement en base terminé.")

if __name__ == "__main__":
    main()
