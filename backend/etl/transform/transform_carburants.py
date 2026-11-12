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

LES STATIONS DOUTEUSES (carte #180, 11 novembre 2026)
Des signaux (signal, détail), comme transform_osm.osm_signals : load_carburants les écrit, poi_triage_service masque
la station tant qu'un humain ne les a pas relus, et la réaffiche quand ils n'ont plus lieu d'être.
    station_douteuse : une station OSM porte l'identifiant de l'État, mais à plus de REF_MAX_M (le Carrefour de
                       Locmaria-Plouzané, 29290003, à 1 096 m le 9 novembre) : l'une des deux positions est fausse ;
    doublon_station  : une station muette (rien déclaré depuis FROZEN_DAYS jours, ni prix ni rupture) à moins de
                       TWIN_MAX_M d'une station active. Le Carrefour Contact de Plouguerneau, déclaré deux fois :
                       29880005 muet depuis le 21 septembre, 29880006 à 9 m, avec les prix du jour ;
    station_muette   : une station muette sans voisine active : elle a peut-être fermé ;
    station_absente  : une station en base que le fichier ne contient plus. Le fichier « instantané » ne porte aucune
                       fermeture (0 balise le 11 novembre sur 9 827 stations) : une station fermée en sort.
Une station muette reste longtemps dans le fichier : 225 jours pour la plus vieille de France le 11 novembre.
Les dernières nouvelles d'une station comptent aussi ses ruptures : à Quimper, une station sans aucun prix déclare
ses ruptures chaque jour, elle est vivante.
"""
import re
import xml.etree.ElementTree as ET
from datetime import datetime

from utils.geo_utils import get_bounding_box, haversine_distance_km

REF_MAX_M = 1000          # au-delà, même avec le bon identifiant, l'une des deux positions est fausse
NEAR_MAX_M = 50
FROZEN_DAYS = 30          # sans nouvelles depuis plus longtemps, une station est « muette »
TWIN_MAX_M = 50           # une station muette et une active plus près que ça : sans doute la même pompe
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


def link_signals(station: dict, osm_stations: list) -> list:
    """Ce que le lien avec OSM signale sur une station de l'État : le même identifiant, trop loin pour être cru."""
    for osm in osm_stations:
        if osm["latitude"] is not None and osm["ref"] == station["pdv_id"]:
            distance = _distance_m(station, osm)
            if distance > REF_MAX_M:
                return [("station_douteuse", {
                    "raison": f"une station OSM porte son identifiant de l'État, mais à {distance:.0f} m",
                    "osm_element": osm["osm_element"], "nom_osm": osm["name"] or osm["brand"],
                    "distance_m": round(distance)})]
    return []


def last_news(prices: list) -> datetime | None:
    """Les dernières nouvelles d'une station : son prix déclaré ou sa rupture la plus récente."""
    days = [price.get(key) for price in prices for key in ("releve_le", "rupture_debut") if price.get(key)]
    return max(days) if days else None


def file_signals(stations: list, missing: list, now: datetime) -> dict:
    """
    {pdv_id: [(signal, détail)]} de toutes les stations : celles du fichier (pdv_id, poi_id, name, address, position de
    l'État, last_news) et celles de la base que le fichier ne contient plus (pdv_id). Une liste vide : rien à signaler.
    Une station muette près d'une active est un doublon, pas une station muette.
    """
    def silent(station):
        return station["last_news"] is None or (now - station["last_news"]).days > FROZEN_DAYS

    signals = {station["pdv_id"]: [("station_absente", {"raison": "absente du fichier de l'État, qui ne la déclare plus"})]
               for station in missing}
    active = [station for station in stations if not silent(station)]
    for station in stations:
        signals[station["pdv_id"]] = []
        if not silent(station):
            continue
        since = f"depuis le {station['last_news']:%d/%m/%Y}" if station["last_news"] else "jamais"
        twins = sorted(((1000 * haversine_distance_km(station["latitude"], station["longitude"], other["latitude"],
                                                      other["longitude"]), other["pdv_id"], other) for other in active),
                       key=lambda twin: twin[:2])
        twins = [(distance, other) for distance, _, other in twins if distance <= TWIN_MAX_M]
        if twins:
            distance, other = twins[0]
            signals[station["pdv_id"]].append(("doublon_station", {
                "raison": f"rien déclaré {since}, une station active déclare à côté", "distance_m": round(distance),
                "autre_id": other["poi_id"], "autre_nom": other["name"], "autre_adresse": other.get("address")}))
        else:
            signals[station["pdv_id"]].append(("station_muette", {"raison": f"rien déclaré à l'État {since}"}))
    return signals


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
