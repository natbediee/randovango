#!/usr/bin/env python3
"""
Analyse tous les fichiers OSM JSON dans data/in/osm et extrait les POI principaux.
Résultat sauvegardé dans data/in/osm_analysis.json
"""

import json
import sys
from pathlib import Path

# Liste des types d'amenity OSM à extraire (modifiable)
TYPES_AMENITY = [
    "parking", "drinking_water", "restaurant", "toilets", "pharmacy", "fuel", "cafe", "bar", "bank", "hospital"
]
# Liste des types de shop OSM à extraire (modifiable)
TYPES_SHOP = [
    "supermarket", "convenience", "bakery", "butcher", "greengrocer", "mall", "department_store"
]

def extract_poi(element):
    """
    Extrait les infos principales d'un POI OSM (node/way/relation)
    """
    tags = element.get("tags", {})
    amenity = tags.get("amenity")
    shop = tags.get("shop")
    tourism = tags.get("tourism")
    information = tags.get("information")
    natural = tags.get("natural")
    historic = tags.get("historic")
    leisure = tags.get("leisure")
    building = tags.get("building")
    # Récupère la position : lat/lon pour node, sinon center pour way/relation
    lat = element.get("lat")
    lon = element.get("lon")
    if lat is None or lon is None:
        center = element.get("center")
        if center:
            lat = center.get("lat")
            lon = center.get("lon")
    # Extraction POI : on prend tout ce qui a au moins un tag d'intérêt
    if amenity or shop or tourism or information or natural or historic or leisure or building:
        # Priorité pour le type principal
        type_main = amenity or shop or tourism or information or natural or historic or leisure or building
        return {
            "osm_id": element.get("id"),
            "osm_type": element.get("type"),
            "type_amenity": type_main,
            "nom": tags.get("name", ""),
            "latitude": lat,
            "longitude": lon,
            "tags": tags
        }
    return None

def analyze_osm_file(file_path):
    """
    Analyse un fichier OSM JSON et retourne la liste des POI extraits
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        elements = data.get("elements", [])
        print(f"  > {len(elements)} éléments dans {file_path}")
        pois = []
        type_counter = {}
        for el in elements:
            poi = extract_poi(el)
            if poi:
                pois.append(poi)
        print(f"  > {len(pois)} POI extraits après filtrage")
        # Bilan par type
        for poi in pois:
            t = poi["type_amenity"]
            type_counter[t] = type_counter.get(t, 0) + 1
        print("  > Bilan par type:")
        for t, count in sorted(type_counter.items(), key=lambda x: -x[1]):
            print(f"    - {t}: {count}")
        # Détail pour les POI d'information
        info_pois = [poi for poi in pois if poi["type_amenity"] == "information"]
        if info_pois:
            subtype_counter = {}
            for poi in info_pois:
                tags = poi.get("tags", {})
                subtype = tags.get("information") or tags.get("board_type") or tags.get("description") or "autre"
                subtype_counter[subtype] = subtype_counter.get(subtype, 0) + 1
            print("  > Détail des POI d'information :")
            for st, count in sorted(subtype_counter.items(), key=lambda x: -x[1]):
                print(f"    - {st}: {count}")
        return pois
    except Exception as e:
        print(f"Erreur {file_path}: {e}")
        return []

def main():
    """
    Fonction principale :
    - Si aucun argument : analyse tous les fichiers JSON OSM du dossier
    - Si un argument (nom de fichier) : analyse uniquement ce fichier
    - Sauvegarde le résultat dans un fichier JSON
    """
    osm_dir = Path("data/in/osm")
    all_pois = []

    if len(sys.argv) == 1:
        # Aucun argument : analyse tous les fichiers
        osm_files = list(osm_dir.glob("*.json"))
        print(f"Trouvé {len(osm_files)} fichiers OSM JSON")
        for osm_file in osm_files:
            print(f"Analyse de {osm_file.name}...")
            pois = analyze_osm_file(str(osm_file))
            all_pois.extend(pois)
        output_file = "data/in/osm_analysis.json"
    elif len(sys.argv) == 2:
        # Un argument : analyse uniquement le fichier indiqué
        file_arg = sys.argv[1]
        file_path = osm_dir / file_arg if not file_arg.startswith("/") else Path(file_arg)
        if not file_path.exists():
            print(f"Fichier introuvable : {file_path}")
            sys.exit(1)
        print(f"Analyse de {file_path.name}...")
        all_pois = analyze_osm_file(str(file_path))
        output_file = f"data/in/osm_analysis_{file_path.stem}.json"
    else:
        print("Usage : python analyze_osm.py [nom_du_fichier.json]")
        sys.exit(1)

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(all_pois, f, ensure_ascii=False, indent=2)
    print(f"Analyse terminée ! Résultats dans {output_file}")

if __name__ == "__main__":
    main()
