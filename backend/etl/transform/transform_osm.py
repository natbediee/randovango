import pandas as pd

from backend.utils.logger_util import LoggerUtil

logger = LoggerUtil.get_logger("transform_osm")

def transform_osm(osm_json,city) -> pd.DataFrame:
    """
    Transforme les données OSM JSON extraites en un DataFrame de POI normalisés pour insertion en base.
    Seuls les POI avec nom, type et coordonnées valides sont conservés.
    Les POI de type 'information' ne sont gardés que si leur nom est 'Office du tourisme'.
    Les commerces (shop) sont inclus.
    """
    pois = []
    if not osm_json or 'elements' not in osm_json:
        logger.warning(f"[OSM] Données OSM invalides pour {city}")
        return pd.DataFrame()
    for el in osm_json['elements']:
        # Cas node classique
        if el.get('type') == 'node' and 'tags' in el:
            name = el['tags'].get('name')
            poi_type = (
                el['tags'].get('amenity') or
                el['tags'].get('tourism') or
                el['tags'].get('leisure') or
                el['tags'].get('shop')
            )
            lat = el.get('lat')
            lon = el.get('lon')
            website = el['tags'].get('website')
            description = el['tags'].get('description')
            if name and poi_type and lat is not None and lon is not None:
                # Filtrage spécial pour 'information'
                if poi_type == 'information' and name != 'Office du tourisme':
                    continue
                poi = {
                    'osm_id': el.get('id'),
                    'name': name,
                    'type': poi_type,
                    'lat': lat,
                    'lon': lon,
                    'source': 'osm'
                }
                if website:
                    poi['website'] = website
                if description:
                    poi['description'] = description
                pois.append(poi)
        # Cas plage (way avec natural=beach)
        elif el.get('type') == 'way' and 'tags' in el and el['tags'].get('natural') == 'beach':
            name = el['tags'].get('name') or el['tags'].get('alt_name')
            poi_type = 'beach'
            center = el.get('center')
            website = el['tags'].get('website')
            description = el['tags'].get('description')
            if name and center and center.get('lat') is not None and center.get('lon') is not None:
                poi = {
                    'osm_id': el.get('id'),
                    'name': name,
                    'type': poi_type,
                    'lat': center['lat'],
                    'lon': center['lon'],
                    'source': 'osm'
                }
                if website:
                    poi['website'] = website
                if description:
                    poi['description'] = description
                pois.append(poi)
    df = pd.DataFrame(pois)
    logger.info(f"[OSM] {len(df)} POI valides extraits pour {city}")
    return df
