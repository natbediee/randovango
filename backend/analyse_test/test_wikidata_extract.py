import json
from backend.etl.extract.api_wikidata import extract_wikidata
from backend.etl.transform.transform_wikidata import transform_wikidata
from backend.etl.load.load_poi import load_wikidata_poi

CITY = "Le Conquet"

def main():
    print(f"Extraction Wikidata pour la ville : {CITY}")
    wiki_json = extract_wikidata(CITY)
    # Sauvegarde du JSON extrait
    with open("data/in/wikidata_extract_plougonvelin.json", "w", encoding="utf-8") as f:
        json.dump(wiki_json, f, ensure_ascii=False, indent=2)
    print(f"Données Wikidata brutes : {json.dumps(wiki_json)[:500]} ...\n")
    df_wiki = transform_wikidata(wikidata_json= wiki_json, city_name=CITY)
    print(f"DataFrame Wikidata transformé :\n{df_wiki.head()}\n")
    load_wikidata_poi(df_wiki=df_wiki, city_name=CITY)
    print("Chargement en base terminé.")

if __name__ == "__main__":
    main()
