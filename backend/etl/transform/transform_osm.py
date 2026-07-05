import pandas as pd

from utils.logger_util import LoggerUtil

logger = LoggerUtil.get_logger("etl_osm")

# Sur OSM, ces équipements n'ont quasiment jamais de tag 'name' (contrairement
# à un restaurant ou une pharmacie). Sans nom de secours, ils étaient rejetés
# silencieusement alors que ce sont les services essentiels en van.
DEFAULT_NAME_BY_TYPE = {
    'drinking_water': "Point d'eau potable",
    'toilets': 'Toilettes publiques',
    'shower': 'Douche publique',
    'sanitary_dump_station': 'Vidange camping-car',
    'waste_disposal': 'Poubelle',
    'shelter': 'Abri',
}

def build_address_from_tags(tags: dict) -> str | None:
    """
    Compose une adresse lisible ("12 Rue de la Mairie, 29880 Plouguerneau") à
    partir des tags addr:* d'OSM, quand au moins la rue est renseignée.
    """
    street = tags.get('addr:street')
    if not street:
        return None
    housenumber = tags.get('addr:housenumber')
    postcode = tags.get('addr:postcode')
    city = tags.get('addr:city')

    street_part = f"{housenumber} {street}" if housenumber else street
    locality_part = f"{postcode} {city}" if postcode and city else (postcode or city or '')

    return f"{street_part}, {locality_part}" if locality_part else street_part


def transform_osm(osm_json : dict,city : str) -> pd.DataFrame:
    """
    Transforme les données OSM JSON extraites en un DataFrame de POI normalisés pour insertion en base.
    Seuls les POI avec nom, type et coordonnées valides sont conservés.
    Les POI de type 'information' ne sont gardés que si leur nom est 'Office du tourisme'.
    Les commerces (shop) sont inclus.
    """
    pois = []
    if not osm_json or 'elements' not in osm_json:
        logger.warning(f"[transform] Données OSM invalides pour {city}")
        return pd.DataFrame()
    for el in osm_json['elements']:
        if 'tags' not in el:
            continue
        tags = el['tags']

        # Coordonnées : un node a directement lat/lon, un way/relation n'a que
        # le centre de son polygone (renvoyé par "out center"). Beaucoup de
        # supermarchés, stations-service, etc. sont mappés comme des bâtiments
        # (way) sur OSM : sans ce centre, ils étaient tous silencieusement perdus.
        if el.get('type') == 'node':
            lat, lon = el.get('lat'), el.get('lon')
        else:
            center = el.get('center') or {}
            lat, lon = center.get('lat'), center.get('lon')

        name = tags.get('name') or tags.get('alt_name')
        poi_type = (
            tags.get('amenity') or
            tags.get('tourism') or
            tags.get('leisure') or
            tags.get('shop') or
            ('beach' if tags.get('natural') == 'beach' else None)
        )
        website = tags.get('website')
        description = tags.get('description')
        address = build_address_from_tags(tags)

        if not name:
            name = DEFAULT_NAME_BY_TYPE.get(poi_type)

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
            if address:
                poi['address'] = address
            pois.append(poi)
    df = pd.DataFrame(pois)
    logger.info(f"[transform] {len(df)} POI valides extraits pour {city}")
    return df
