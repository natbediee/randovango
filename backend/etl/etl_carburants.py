"""
Les stations-service et leurs prix, depuis prix-carburants.gouv.fr : extraction, transformation, chargement.
Gratuit : aucun agent, aucune recherche web. Un fichier d'environ 1 Mo pour toute la France, puis Overpass par ville.

Deux façons de passer :
    par ville  : les stations à moins de DISTANCE_KM du centre, reliées aux stations OSM pour avoir leur marque ;
    prix       : les prix des stations déjà en base, sans Overpass. Le lien avec OSM déjà fait est gardé.

UTILISATION (depuis backend/) :
    python -m etl.etl_carburants --ville Plougonvelin --essai      # n'écrit rien : affiche ce qui serait chargé
    python -m etl.etl_carburants --ville Plougonvelin --ville Saint-Renan
    python -m etl.etl_carburants --toutes                           # toutes les villes de la table cities
    python -m etl.etl_carburants --prix                             # le rafraîchissement quotidien des prix
"""
import argparse
from datetime import datetime

from etl.extract.api_carburants import download_state_file, extract_osm_fuel
from etl.load.load_carburants import known_stations, load_stations, mark_prices_read
from etl.transform.transform_carburants import (keep_near, link_to_osm, osm_station, parse_state_file,
                                                station_rows)
from utils.db_utils import get_all_city_ids
from utils.geo_utils import get_city_center, haversine_distance_km
from utils.logger_util import LoggerUtil

logger = LoggerUtil.get_logger("etl_carburants")

DISTANCE_KM = 5     # le carré de l'ETL OSM (api_osm.extract_osm) et de l'étape 4 (step4_services.js)


def _read_state_file() -> list | None:
    xml = download_state_file()
    return parse_state_file(xml) if xml else None


def city_rows(city: str, stations: list) -> tuple | None:
    """(lignes à charger, stations OSM seules) pour une ville. None si la ville ou Overpass manquent."""
    latitude, longitude = get_city_center(city)
    if latitude is None:
        logger.error(f"[ETL] : {city} absente de la table cities")
        return None
    nearby = keep_near(stations, latitude, longitude, DISTANCE_KM)
    elements = extract_osm_fuel(latitude, longitude, DISTANCE_KM, city)
    if elements is None:
        logger.error(f"[ETL] : Overpass muet pour {city} : stations non chargées, à repasser")
        return None
    osm_stations = [osm_station(e) for e in elements]
    read_at = datetime.now().replace(microsecond=0)
    rows, linked = [], set()
    for station in nearby:
        osm, link = link_to_osm(station, osm_stations)
        if osm:
            linked.add(osm["osm_element"])
        rows.append(station_rows(station, osm, link, read_at))
    osm_only = [osm for osm in osm_stations if osm["osm_element"] not in linked]
    logger.info(f"[ETL] : {city} : {len(rows)} stations de l'État, {len(osm_only)} stations OSM seules (masquées)")
    return rows, osm_only


def run_city_etl(city: str, dry_run: bool = False, stations: list | None = None) -> int | None:
    """Renvoie le nombre de stations chargées (ou qui le seraient), None en cas d'échec."""
    stations = stations if stations is not None else _read_state_file()
    if stations is None:
        return None
    result = city_rows(city, stations)
    if result is None:
        return None
    rows, osm_only = result
    if dry_run:
        _print_report(city, rows, osm_only)
        return len(rows)
    return load_stations(rows, city)


def refresh_prices(dry_run: bool = False) -> int | None:
    """
    Les prix et l'état des stations déjà en base, sans redemander OSM. Lancé une fois par jour au début d'un voyage
    (api/routers/step1.py) ; la date du passage réussi est notée dans sources.lu_le. None si le fichier manque.
    """
    stations = _read_state_file()
    if stations is None:
        return None
    known = known_stations()
    read_at = datetime.now().replace(microsecond=0)
    rows = []
    for station in stations:
        stored = known.get(station["pdv_id"])
        if not stored:
            continue
        osm = None
        if stored["osm_element"]:
            osm = {"osm_element": stored["osm_element"], "name": stored["name"], "brand": stored["marque"],
                   "latitude": stored["latitude"], "longitude": stored["longitude"]}
        rows.append(station_rows(station, osm, stored["lien_osm"], read_at))
    missing = len(known) - len(rows)
    if missing:
        logger.warning(f"[ETL] : {missing} stations en base absentes du fichier : leurs derniers prix restent, datés")
    if dry_run:
        print(f"{len(rows)} stations seraient mises à jour, {missing} absentes du fichier")
        return len(rows)
    loaded = load_stations(rows, None)
    mark_prices_read(read_at)
    return loaded


def _print_report(city: str, rows: list, osm_only: list) -> None:
    print(f"\n=== {city} : {len(rows)} stations de l'État ===")
    for row in rows:
        station, poi = row["station"], row["poi"]
        gap = haversine_distance_km(station["latitude_etat"], station["longitude_etat"], poi["latitude"],
                                    poi["longitude"]) * 1000
        print(f"- {poi['name']} [{station['lien_osm']}, {gap:.0f} m de la position de l'État] "
              f"{poi['address'] or '(adresse inutilisable : ' + str(station['adresse_etat']) + ')'}")
        if station["fermeture_type"]:
            print(f"    fermeture {station['fermeture_type']} depuis {station['fermeture_debut']}")
        for price in row["prix"]:
            if price["prix"] is not None:
                print(f"    {price['carburant']:7} {price['prix']:.3f} €  relevé le {price['releve_le']}"
                      + (f"  (rupture {price['rupture_type']})" if price["rupture_type"] else ""))
            elif price["rupture_type"] == "temporaire":
                print(f"    {price['carburant']:7} rupture temporaire depuis {price['rupture_debut']}")
    for osm in osm_only:
        print(f"  OSM seule, masquée : {osm['name'] or osm['brand'] or '?'} ({osm['osm_element']})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Stations-service et prix des carburants (prix-carburants.gouv.fr)")
    parser.add_argument("--ville", action="append", help="une ville de la table cities (option répétable)")
    parser.add_argument("--toutes", action="store_true", help="toutes les villes de la table cities")
    parser.add_argument("--prix", action="store_true", help="rafraîchir les prix des stations déjà en base")
    parser.add_argument("--essai", action="store_true", help="n'écrit rien en base, affiche le résultat")
    args = parser.parse_args()
    if args.prix:
        refresh_prices(dry_run=args.essai)
        return
    cities = [name for _, name in get_all_city_ids()] if args.toutes else (args.ville or [])
    if not cities:
        parser.error("--ville, --toutes ou --prix")
    stations = _read_state_file()
    if stations is None:
        return
    for city in cities:
        run_city_etl(city, dry_run=args.essai, stations=stations)


if __name__ == "__main__":
    main()
