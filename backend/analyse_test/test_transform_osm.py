import json
import os
import sys

# Permet l'exécution avec python3 -m backend.etl.test_transform_osm
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))
from backend.etl.transform.transform_osm import transform_osm

if __name__ == "__main__":
    osm_path = os.path.join(os.path.dirname(__file__), '../../data/in/osm/osm_data_plougonvelin.json')
    osm_path = os.path.abspath(osm_path)
    with open(osm_path, "r") as f:
        osm_json = json.load(f)
    df = transform_osm(osm_json, filename="osm_data_plougonvelin.json")
    print(f"Nombre de POI valides extraits : {df.shape[0]}")
    print(list(df.columns))
    print("\nAperçu du DataFrame :")
    print(df)
