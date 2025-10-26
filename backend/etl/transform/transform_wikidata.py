from backend.utils.logger_util import LoggerUtil
import pandas as pd

logger = LoggerUtil.get_logger("transform_wikidata")

def extract_lat_lon_from_wkt(wkt)-> tuple:
    # Ex: 'Point(-4.75968 48.36939)' → lon, lat
    try:
        coords = wkt.replace('Point(', '').replace(')', '').split()
        if len(coords) == 2:
            lon, lat = float(coords[0]), float(coords[1])
            return lat, lon
    except Exception:
        pass
    return None, None

def transform_wikidata(wikidata_json, city_name)-> pd.DataFrame:
    """
    Transforme les données Wikidata extraites en une liste de POI normalisés pour insertion en base.
    Extraction des coordonnées depuis 'coord' (WKT), et du type depuis 'types' ou 'typeLabels'.
    """
    pois = []
    if not wikidata_json or 'results' not in wikidata_json or 'bindings' not in wikidata_json['results']:
        logger.warning(f"[Wikidata] Données Wikidata invalides pour {city_name}")
        return pd.DataFrame()
    for item in wikidata_json['results']['bindings']:
        wikidata_id = item.get('item', {}).get('value', None)
        name = item.get('itemLabel', {}).get('value', None)
        # typeLabel n'existe pas toujours, utiliser 'types' sinon
        poi_type = item.get('typeLabel', {}).get('value', None) or item.get('types', {}).get('value', None)
        # Exclure les monuments
        if poi_type and 'monument' in poi_type.lower():
            continue
        # Extraire coordonnées depuis 'coord' (WKT)
        coord_wkt = item.get('coord', {}).get('value', None)
        # Extraire l'URL de l'image si présente
        image_url = item.get('image', {}).get('value', None)
        # Extraire la description si présente
        description = item.get('itemDescription', {}).get('value', None)
        if coord_wkt:
            lat, lon = extract_lat_lon_from_wkt(coord_wkt)
        else:
            lat, lon = None, None
        if wikidata_id and name and lat is not None and lon is not None:
            poi = {
                'wikidata_id': wikidata_id,
                'name': name,
                'type': poi_type,
                'lat': lat,
                'lon': lon,
                'image_url': image_url,
                'source': 'wikidata'
            }
            if description:
                poi['description'] = description
            pois.append(poi)
    df = pd.DataFrame(pois)
    logger.info(f"[Wikidata] {len(df)} POI valides extraits de {city_name}")
    return df
