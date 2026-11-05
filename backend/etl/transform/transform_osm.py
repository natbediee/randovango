import re
import unicodedata

import pandas as pd

from utils.geo_utils import haversine_distance_km
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

# Le lien d'un lieu, du plus utile au moins utile. Beaucoup de contributeurs n'écrivent
# que contact:website, ou seulement la page Facebook : 159 restaurants sur 1 775 sans lien
# en avaient un dans OSM, ignoré quand seul le tag website était lu.
OSM_WEBSITE_TAGS = ("website", "contact:website", "url")
OSM_SOCIAL_TAGS = {"contact:facebook": "facebook.com", "facebook": "facebook.com",
                   "contact:instagram": "instagram.com", "instagram": "instagram.com"}
OSM_LINK_TAGS = OSM_WEBSITE_TAGS + tuple(OSM_SOCIAL_TAGS)
LIFECYCLE_PREFIXES = ("disused:", "abandoned:", "was:", "closed:", "removed:", "demolished:", "razed:", "former:")
MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
_MONTH_NAMES = "|".join(MONTHS)
_MONTH_RANGE = re.compile(rf"\b({_MONTH_NAMES})\b(?:\s*\d{{1,2}})?(?:\s*-\s*(?:({_MONTH_NAMES})\b)?)?")
# Un objet OSM relu par identifiant n'est le même lieu que s'il n'a pas bougé.
OSM_MATCH_KM = 1
_NAME_STOPWORDS = set("""
le la les de du des l d was restaurant creperie boulangerie patisserie pharmacie cafe bar
""".split())


def normalize_osm_link(tag: str, value: str) -> str | None:
    """
    Rend une adresse complète. Un tag social contient parfois seulement le nom de la page
    (« Aber-Wrach-Huîtres-Bar-1043609052472772 ») ou un numéro mal saisi (« https://100091272374097 »).
    """
    value = (value or "").split(";")[0].strip()
    if not value:
        return None
    domain = OSM_SOCIAL_TAGS.get(tag)
    if domain:
        if domain in value:
            return value if value.startswith("http") else f"https://{value}"
        page = re.sub(r"^https?://", "", value).lstrip("@/")
        return f"https://www.{domain}/{page}"
    return value if value.startswith(("http://", "https://")) else f"https://{value}"


def osm_link(tags: dict) -> str | None:
    """Le meilleur lien de l'objet : son site, sinon sa page Facebook ou Instagram."""
    for tag in OSM_LINK_TAGS:
        link = normalize_osm_link(tag, tags.get(tag))
        if link:
            return link
    return None


def months_open(hours: str | None) -> list | None:
    """
    Mois d'ouverture d'après opening_hours, ou None si l'année entière ou illisible.
    « Apr-Sep » -> avril à septembre ; « Sep-Jun Tu-Sa ; Jul-Aug Mo-Su » couvre toute l'année.
    """
    if not hours or not _MONTH_RANGE.search(hours):
        return None
    opened, closed = set(), set()
    for rule in hours.split(";"):
        rule = rule.strip()
        found = _MONTH_RANGE.findall(rule)
        is_closed = re.search(r"\b(off|closed)\b", rule)
        if not found:
            if rule and not is_closed and not rule.startswith("PH"):
                return None  # une règle sans mois : ouvert toute l'année
            continue
        months = set()
        for start, end in found:
            first, last = MONTHS.index(start), MONTHS.index(end or start)
            months |= {(first + step) % 12 for step in range((last - first) % 12 + 1)}
        (closed if is_closed else opened).update(months)
    result = (opened or set(range(12))) - closed
    return [MONTHS[month] for month in sorted(result)] if len(result) < 12 else None


def osm_details(tags: dict) -> dict:
    """Ce qu'un objet OSM dit de plus que son nom et son type, à garder pour la vérification des lieux."""
    return {
        "phone": tags.get("phone") or tags.get("contact:phone"),
        "opening_hours": tags.get("opening_hours"),
        "seasonal": tags.get("seasonal"),
        "months_open": months_open(tags.get("opening_hours")),
    }


def pick_osm_element(elements: list, latitude: float, longitude: float) -> dict | None:
    """Parmi le node, le way et la relation de même numéro, celui qui est à l'emplacement du POI."""
    best, best_distance = None, OSM_MATCH_KM
    for element in elements:
        lat = element.get("lat") or (element.get("center") or {}).get("lat")
        lon = element.get("lon") or (element.get("center") or {}).get("lon")
        if lat is None or lon is None:
            continue
        distance = haversine_distance_km(latitude, longitude, lat, lon)
        if distance < best_distance:
            best, best_distance = element, distance
    return best


def is_real_rename(base_name: str, osm_name: str | None) -> bool:
    """Aucun mot propre en commun : « Kous » devenu « Tisto ». Une faute (« La Diff », « La Dif ») passera : c'est relu."""
    if not osm_name or osm_name.lower().startswith("was:"):
        return False
    words = set(_name_words(base_name)) - _NAME_STOPWORDS
    return not (words & set(_name_words(osm_name)))


def _name_words(name: str) -> list:
    ascii_name = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    return re.findall(r"[a-z0-9]+", ascii_name)


def osm_signals(poi: dict, element: dict | None) -> list:
    """
    Ce qu'OSM signale sur un commerce de la base : autant de lignes (signal, détail) à relire.
    OSM peut être en retard ou se tromper : rien n'est appliqué sans relecture.
    """
    if element is None:
        return [("absent_osm", {"nom": poi["name"]})]
    tags = element.get("tags", {})
    signals = []
    main_tag = tags.get("amenity") or tags.get("shop")
    lifecycle = {key: value for key, value in tags.items() if key.startswith(LIFECYCLE_PREFIXES)}
    if not main_tag or main_tag.startswith("was:"):
        if any(key.endswith((":amenity", ":shop")) for key in lifecycle):
            signals.append(("fermeture_osm", {"tags": lifecycle, "nom_osm": tags.get("name")}))
    elif is_real_rename(poi["name"], tags.get("name")):
        signals.append(("renommage_osm", {"ancien_nom": poi["name"], "nom_osm": tags["name"]}))
    if not poi.get("url"):
        link = osm_link(tags)
        if link:
            signals.append(("lien_osm", {"url": link}))
    details = osm_details(tags)
    if details["months_open"] or details["seasonal"]:
        signals.append(("saison_osm", {"mois": details["months_open"], "seasonal": details["seasonal"],
                                       "opening_hours": details["opening_hours"]}))
    return signals


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
            tags.get('craft') or
            ('beach' if tags.get('natural') == 'beach' else None)
        )
        website = osm_link(tags)
        details = osm_details(tags)
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
            if details['phone'] or details['opening_hours'] or details['seasonal']:
                poi['osm_details'] = details
            pois.append(poi)
    df = pd.DataFrame(pois)
    logger.info(f"[transform] {len(df)} POI valides extraits pour {city}")
    return df
