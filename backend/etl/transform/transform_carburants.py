"""
Du fichier de l'État et des stations OSM aux lignes à charger. Aucune base, aucun réseau : tout se teste à la main.

LE FICHIER DE L'ÉTAT PROUVE QUE LA STATION EXISTE, OSM NE DONNE QUE LA MARQUE
Pilote du 7 novembre 2026 (Plougonvelin, Saint-Renan, Ploudalmézeau, Plouarzel) : 6 stations, les 6 reliées à OSM
par l'étiquette ref:FR:prix-carburants. Le Total de Portsall, connu d'OSM seul, existe mais ne déclare pas ses prix :
une station OSM sans station de l'État n'est jamais chargée.

LA POSITION VIENT D'OSM
L'État arrondit parfois au millième de degré : 523 m d'écart pour le Leclerc de Keruscat, 389 m pour la Station U
de Plouarzel, alors que l'identifiant dit que c'est la même station. Quand l'identifiant correspond, on lui fait donc
confiance jusqu'à REF_MAX_M, et la position affichée est celle d'OSM, juste à 4 m près à Saint-Renan.

SANS IDENTIFIANT : UNE SEULE STATION OSM TOUT PRÈS, SINON RIEN
Une station OSM sans étiquette, seule à moins de NEAR_MAX_M et sans autre code postal, est reliée « par proximité ».
Deux candidates, ou une trop loin : doute, donc pas de marque. La station reste montrée, sous « Station-service ».

L'ADRESSE DE L'ÉTAT N'EST PAS TOUJOURS UNE ADRESSE
À Plouarzel, le champ adresse contient « SAS SNDL MENEZ CRENN », le nom de la société exploitante.
"""
import re
import xml.etree.ElementTree as ET
from datetime import datetime

from utils.geo_utils import get_bounding_box, haversine_distance_km

REF_MAX_M = 1000          # au-delà, même avec le bon identifiant, l'une des deux positions est fausse
NEAR_MAX_M = 50
DEFAULT_NAME = "Station-service"
COMPANY_FORM = re.compile(r"^(SAS|SASU|SARL|EURL|SA|SNC|SCI|SELARL)\b", re.IGNORECASE)


def _date(text: str | None) -> datetime | None:
    """Les dates du fichier : « 2026-11-07 08:13:42 », parfois « 2026-11-07T08:13:42 », parfois vides."""
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.strip().replace("T", " "))
    except ValueError:
        return None


def _hours(pdv: ET.Element) -> tuple:
    """
    (automate 24h/24 : 1, 0 ou None, {jour: « ferme » ou [[ouverture, fermeture], ...]}).
    Un jour avec ferme="" et sans créneau est ouvert sans horaires indiqués (Intermarché de Plougonvelin, 24h/24) :
    une liste vide, pas « ferme ». Les heures sont au format du fichier, « 07.00 ».
    """
    node = pdv.find("horaires")
    if node is None:
        return None, None
    automate = node.get("automate-24-24")
    days = {}
    for day in node.findall("jour"):
        if day.get("ferme") == "1":
            days[day.get("nom")] = "ferme"
        else:
            days[day.get("nom")] = [[h.get("ouverture"), h.get("fermeture")] for h in day.findall("horaire")]
    return (int(automate) if automate in ("0", "1") else None), (days or None)


def parse_state_file(xml: bytes) -> list:
    """Une station par nœud <pdv>. Les coordonnées du fichier sont multipliées par 100 000."""
    stations = []
    for pdv in ET.fromstring(xml).iter("pdv"):
        try:
            latitude, longitude = float(pdv.get("latitude")) / 100000, float(pdv.get("longitude")) / 100000
        except (TypeError, ValueError):
            continue
        automate, hours = _hours(pdv)
        fuels = {}
        for price in pdv.findall("prix"):
            fuels[price.get("nom")] = {"prix": float(price.get("valeur")), "releve_le": _date(price.get("maj")),
                                       "rupture_type": None, "rupture_debut": None, "rupture_fin": None}
        for shortage in pdv.findall("rupture"):
            fuel = fuels.setdefault(shortage.get("nom"), {"prix": None, "releve_le": None})
            fuel.update({"rupture_type": shortage.get("type"), "rupture_debut": _date(shortage.get("debut")),
                         "rupture_fin": _date(shortage.get("fin"))})
        closure = pdv.find("fermeture")
        stations.append({
            "pdv_id": pdv.get("id"),
            "latitude": latitude,
            "longitude": longitude,
            "code_postal": pdv.get("cp"),
            "route": pdv.get("pop"),
            "adresse": (pdv.findtext("adresse") or "").strip() or None,
            "ville": (pdv.findtext("ville") or "").strip() or None,
            "automate_24_24": automate,
            "horaires": hours,
            "services": [s.text.strip() for s in pdv.iter("service") if s.text and s.text.strip()] or None,
            "fermeture_type": closure.get("type") if closure is not None else None,
            "fermeture_debut": _date(closure.get("debut")) if closure is not None else None,
            "fermeture_fin": _date(closure.get("fin")) if closure is not None else None,
            "carburants": fuels,
        })
    return stations


def keep_near(stations: list, latitude: float, longitude: float, distance_km: float) -> list:
    """Les stations du carré de distance_km autour du point : le même carré que l'ETL OSM et l'étape 4."""
    min_lat, min_lon, max_lat, max_lon = get_bounding_box(latitude, longitude, distance_km)
    return [s for s in stations if min_lat <= s["latitude"] <= max_lat and min_lon <= s["longitude"] <= max_lon]


def osm_station(element: dict) -> dict:
    tags = element.get("tags", {})
    return {
        "osm_element": f"{element['type']}/{element['id']}",
        "latitude": element.get("lat") or element.get("center", {}).get("lat"),
        "longitude": element.get("lon") or element.get("center", {}).get("lon"),
        "name": tags.get("name"),
        "brand": tags.get("brand"),
        "ref": tags.get("ref:FR:prix-carburants"),
        "postcode": tags.get("addr:postcode"),
    }


def _distance_m(station: dict, osm: dict) -> float:
    return 1000 * haversine_distance_km(station["latitude"], station["longitude"], osm["latitude"], osm["longitude"])


def link_to_osm(station: dict, osm_stations: list) -> tuple:
    """(station OSM ou None, « ref_osm », « proximite » ou « aucun »)."""
    located = [osm for osm in osm_stations if osm["latitude"] is not None]
    by_ref = [osm for osm in located if osm["ref"] == station["pdv_id"] and _distance_m(station, osm) <= REF_MAX_M]
    if by_ref:
        return by_ref[0], "ref_osm"
    close = [osm for osm in located if _distance_m(station, osm) <= NEAR_MAX_M]
    if len(close) == 1 and not close[0]["ref"] and close[0]["postcode"] in (None, station["code_postal"]):
        return close[0], "proximite"
    return None, "aucun"


def usable_address(station: dict) -> str | None:
    """« 1 Place Léon Cheminant, 29290 Saint-Renan », ou None quand le champ adresse est le nom d'une société."""
    street = station["adresse"]
    if not street or COMPANY_FORM.match(street):
        return None
    town = (station["ville"] or "").title()
    return ", ".join(part for part in (street, f"{station['code_postal'] or ''} {town}".strip()) if part)


def station_rows(station: dict, osm: dict | None, link: str, read_at: datetime) -> dict:
    """Ce qui va dans poi, stations_carburant et prix_carburants pour une station."""
    name = (osm and (osm["name"] or osm["brand"])) or DEFAULT_NAME
    position = osm if osm else station
    return {
        "poi": {"name": name, "latitude": position["latitude"], "longitude": position["longitude"],
                "address": usable_address(station)},
        "station": {
            "pdv_id": station["pdv_id"], "osm_element": osm["osm_element"] if osm else None, "lien_osm": link,
            "marque": (osm and (osm["brand"] or osm["name"])) or None,
            "adresse_etat": station["adresse"], "code_postal": station["code_postal"], "ville_etat": station["ville"],
            "latitude_etat": station["latitude"], "longitude_etat": station["longitude"], "route": station["route"],
            "automate_24_24": station["automate_24_24"], "horaires": station["horaires"],
            "services": station["services"], "fermeture_type": station["fermeture_type"],
            "fermeture_debut": station["fermeture_debut"], "fermeture_fin": station["fermeture_fin"],
            "lu_le": read_at,
        },
        "prix": [{"carburant": fuel, **values} for fuel, values in sorted(station["carburants"].items())],
    }
