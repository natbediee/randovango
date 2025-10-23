#!/usr/bin/env python3
"""
Analyse tous les fichiers GPX dans data/in/gpx et extrait les infos principales.
Résultat sauvegardé dans data/in/gpx_analysis.json
"""

 # import os (non utilisé)
import json
import gpxpy
from pathlib import Path
import math

def haversine_distance(lat1, lon1, lat2, lon2):
    """
    Calcule la distance en kilomètres entre deux points GPS (formule de Haversine)
    """
    R = 6371  # Rayon de la Terre en km
    lat1_rad, lon1_rad = math.radians(lat1), math.radians(lon1)
    lat2_rad, lon2_rad = math.radians(lat2), math.radians(lon2)
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    a = math.sin(dlat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

def elevation_stats(points):
    """
    Calcule les statistiques d'altitude : min, max, dénivelé positif et négatif
    """
    elevations = [p.elevation for p in points if p.elevation is not None]
    if not elevations:
        return {"min": 0, "max": 0, "positive": 0, "negative": 0}
    min_elev = min(elevations)
    max_elev = max(elevations)
    positive = negative = 0
    for i in range(1, len(elevations)):
        diff = elevations[i] - elevations[i-1]
        if diff > 0:
            positive += diff
        elif diff < 0:
            negative += abs(diff)
    return {"min": min_elev, "max": max_elev, "positive": positive, "negative": negative}

def analyze_gpx_file(file_path):
    """
    Analyse un fichier GPX et extrait les informations principales :
    - nom, description
    - waypoints (étapes)
    - distance totale
    - stats d'altitude
    - coordonnées de départ
    """
    try:
        # Lecture et parsing du fichier GPX
        with open(file_path, 'r', encoding='utf-8') as f:
            gpx = gpxpy.parse(f.read())

        # Nom et description de la randonnée
        nom = gpx.name or Path(file_path).stem
        description = gpx.description or ""

        # Extraction des waypoints (étapes)
        waypoints = []
        for wpt in gpx.waypoints:
            waypoints.append({
                "nom": wpt.name or "",
                "description": wpt.description or "",
                "latitude": wpt.latitude,
                "longitude": wpt.longitude,
                "elevation": wpt.elevation
            })

        # Calcul de la distance totale et collecte des points de trace
        total_distance = 0
        all_points = []
        # Pour chaque segment de trace, calculer la distance et stocker les points
        for track in gpx.tracks:
            for segment in track.segments:
                points = segment.points
                all_points.extend(points)
                for i in range(1, len(points)):
                    p1, p2 = points[i-1], points[i]
                    if p1.latitude and p1.longitude and p2.latitude and p2.longitude:
                        total_distance += haversine_distance(p1.latitude, p1.longitude, p2.latitude, p2.longitude)

        # Coordonnées de départ (premier point de trace)
        depart_lat = all_points[0].latitude if all_points else None
        depart_lon = all_points[0].longitude if all_points else None

        # Statistiques d'altitude
        elev = elevation_stats(all_points)

        # Durée estimée (vitesse moyenne 4,5 km/h)
        duree_estimee = total_distance / 4.5 if total_distance > 0 else 0

        # Retourne toutes les infos extraites sous forme de dictionnaire
        return {
            "fichier": Path(file_path).name,
            "nom": nom,
            "description": description,
            "distance_km": round(total_distance, 2),
            "duree_estimee_heures": round(duree_estimee, 1),
            "depart_latitude": depart_lat,
            "depart_longitude": depart_lon,
            "elevation_min": elev["min"],
            "elevation_max": elev["max"],
            "denivele_positif": round(elev["positive"], 1),
            "denivele_negatif": round(elev["negative"], 1),
            "nombre_waypoints": len(waypoints),
            "nombre_points_trace": len(all_points),
            "waypoints": waypoints
        }
    except Exception as e:
        print(f"Erreur {file_path}: {e}")
        return None

def main():
    """
    Fonction principale :
    - Liste tous les fichiers GPX du dossier
    - Analyse chaque fichier
    - Sauvegarde le résultat dans un fichier JSON
    """
    gpx_dir = Path("data/in/gpx")
    gpx_files = list(gpx_dir.glob("*.gpx"))
    print(f"Trouvé {len(gpx_files)} fichiers GPX")
    analyses = []
    for gpx_file in gpx_files:
        print(f"Analyse de {gpx_file.name}...")
        result = analyze_gpx_file(str(gpx_file))
        if result:
            analyses.append(result)
    # Sauvegarde des résultats dans un fichier JSON
    with open("data/in/gpx_analysis.json", "w", encoding="utf-8") as f:
        json.dump(analyses, f, ensure_ascii=False, indent=2)
    print("Analyse terminée ! Résultats dans data/in/gpx_analysis.json")

# Point d'entrée du script
if __name__ == "__main__":
    main()
