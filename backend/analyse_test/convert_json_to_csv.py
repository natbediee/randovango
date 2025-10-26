#!/usr/bin/env python3
"""Conversion améliorée pour un fichier OSM JSON spécifique.
Aplati les tags JSON en colonnes distinctes dans le CSV.
Usage: python convert_ploudiry.py
"""
import json
import csv
from pathlib import Path

INPUT = Path(__file__).parent / 'osm_data_plougonvelin.json'
OUTPUT = Path(__file__).parent / 'osm_data_plougonvelin.csv'

with INPUT.open('r', encoding='utf-8') as f:
    data = json.load(f)

elements = data.get('elements', [])

# Collecter toutes les clés de tags pour créer des colonnes dynamiques
all_keys = set()
for el in elements:
    tags = el.get('tags', {})
    all_keys.update(tags.keys())

# Colonnes fixes + colonnes dynamiques pour les tags
fieldnames = ['id', 'osm_type', 'name', 'lat', 'lon'] + sorted(all_keys)

with OUTPUT.open('w', newline='', encoding='utf-8') as csvf:
    writer = csv.DictWriter(csvf, fieldnames=fieldnames)
    writer.writeheader()

    for el in elements:
        osm_id = el.get('id')
        osm_type = el.get('type')
        tags = el.get('tags', {})
        name = tags.get('name', '')

        lat = None
        lon = None
        if osm_type == 'node':
            lat = el.get('lat')
            lon = el.get('lon')
        else:
            center = el.get('center') or {}
            lat = center.get('lat')
            lon = center.get('lon')

        # Préparer une ligne avec les colonnes fixes et dynamiques
        row = {
            'id': osm_id,
            'osm_type': osm_type,
            'name': name,
            'lat': lat,
            'lon': lon,
        }
        row.update({key: tags.get(key, '') for key in all_keys})

        writer.writerow(row)

print(f'Fichier CSV créé avec tags aplatis : {OUTPUT}')
