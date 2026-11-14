"""
Les pharmacies, depuis le registre FINESS de l'État : extraction, transformation, chargement (carte #194).
Gratuit : aucun agent, aucune recherche web. Un fichier pour toute la France, lu une fois par passage.

Même chemin que les carburants (etl_carburants.py) : l'État prouve que la pharmacie existe. Ici, il donne aussi
le nom, l'adresse et la position ; OSM ne sert qu'à remplacer un nom juridique (transform_pharmacies.py).

La règle de transition est à l'étape 4 (step4.keep_state_pharmacies) : les pharmacies d'OSM d'une commune ne sont
cachées qu'une fois ce passage fait sur elle. Avant, elles restent : une pharmacie, c'est l'urgence du voyageur.

À chaque passage, les pharmacies déjà en base qui ont fermé (ou sont sorties du fichier) sont masquées, dans toute
la France : le fichier est national.

UTILISATION (depuis backend/) :
    python -m etl.etl_pharmacies --ville Plougonvelin --essai     # n'écrit rien : affiche ce qui serait chargé
    python -m etl.etl_pharmacies --ville Plougonvelin --ville Brest
    python -m etl.etl_pharmacies --toutes                          # toutes les villes de la table cities
"""
import argparse
from datetime import date

from etl.extract.api_finess import download_pharmacies
from etl.load.load_pharmacies import hide_closed, known_pharmacies, load_pharmacy_rows, osm_pharmacies_near
from etl.transform.transform_carburants import keep_near
from etl.transform.transform_pharmacies import closures, is_open, pharmacy_row, to_pharmacy
from utils.db_utils import get_all_city_ids
from utils.geo_utils import address_town, get_city_center, town_key
from utils.logger_util import LoggerUtil

logger = LoggerUtil.get_logger("etl_pharmacies")

DISTANCE_KM = 5     # le carré de l'ETL OSM (api_osm.extract_osm) et de l'étape 4 (step4_services.js)


def read_pharmacies() -> list | None:
    """Toutes les pharmacies de FINESS, ouvertes ou fermées. None si le fichier manque."""
    eges = download_pharmacies()
    return [to_pharmacy(ege) for ege in eges] if eges is not None else None


def same_postcodes(nearby: list, located: list) -> list:
    """
    Toutes les pharmacies des codes postaux présents dans la zone, même hors de la zone. L'étape 4 cache les
    pharmacies d'OSM par code postal (step4.keep_state_pharmacies) : un code postal touché doit donc être chargé en
    entier. Essai du 14 novembre 2026 : 20 des 33 pharmacies de Brest seulement dans la zone de 5 km, et 29280 partagé
    entre Plouzané et Locmaria-Plouzané.
    """
    postcodes = {pharmacy["code_postal"] for pharmacy in nearby} - {None}
    return [pharmacy for pharmacy in located if pharmacy["code_postal"] in postcodes]


def city_rows(city: str, pharmacies: list, today: date) -> list | None:
    """
    Les lignes à charger pour une ville : les pharmacies ouvertes des codes postaux de sa zone de DISTANCE_KM.
    None si la ville manque.
    """
    latitude, longitude = get_city_center(city)
    if latitude is None:
        logger.error(f"[ETL] : {city} absente de la table cities")
        return None
    located = [p for p in pharmacies if is_open(p, today) and p["latitude"] is not None]
    chosen = same_postcodes(keep_near(located, latitude, longitude, DISTANCE_KM), located)
    # Les pharmacies OSM d'un carré un peu plus grand : une pharmacie d'un code postal touché peut être hors de la zone.
    osm_pharmacies = osm_pharmacies_near(latitude, longitude, 2 * DISTANCE_KM)
    rows = [pharmacy_row(pharmacy, osm_pharmacies) for pharmacy in chosen]
    logger.info(f"[ETL] : {towns_summary(city, rows)}")
    return rows


def run_city_etl(city: str, pharmacies: list, dry_run: bool = False) -> int | None:
    """Renvoie le nombre de pharmacies chargées (ou qui le seraient), None en cas d'échec."""
    rows = city_rows(city, pharmacies, date.today())
    if rows is None:
        return None
    if dry_run:
        _print_report(city, rows)
        return len(rows)
    return load_pharmacy_rows(rows, city)


def hide_closed_pharmacies(pharmacies: list, dry_run: bool = False) -> int:
    """Les pharmacies déjà en base qui ne sont plus ouvertes dans FINESS : masquées (ou seulement listées en essai)."""
    known = known_pharmacies()
    closed = closures(known, pharmacies, date.today())
    if dry_run:
        for finess, closed_on in closed.items():
            print(f"  serait masquée : pharmacie {finess}, fermée le {closed_on or '? (sortie du fichier)'}")
        return len(closed)
    return hide_closed(closed, known)


def towns_summary(city: str, rows: list) -> str:
    """
    Le compte des pharmacies d'un passage, par commune : « Plougonvelin : 1 pharmacie dans la commune, 6 autour
    (Le Conquet 1, Locmaria-Plouzané 1, Plouzané 4) ». Un passage charge toute la zone de 5 km et ses codes postaux :
    le total seul laissait croire à 7 pharmacies à Plougonvelin, qui n'en a qu'une (essai du 14 novembre 2026).
    """
    names, counts = {}, {}
    for row in rows:
        town = address_town(row["poi"]["address"]) or "commune inconnue"
        key = town_key(town)
        names.setdefault(key, town)
        counts[key] = counts.get(key, 0) + 1
    inside = counts.pop(town_key(city), 0)
    around = ", ".join(f"{names[key]} {count}" for key, count in sorted(counts.items()))
    summary = f"{city} : {inside} pharmacie{'s' if inside > 1 else ''} dans la commune"
    return summary + (f", {sum(counts.values())} autour ({around})" if counts else "")


def _print_report(city: str, rows: list) -> None:
    print(f"\n=== {towns_summary(city, rows)} ===")
    for row in rows:
        poi = row["poi"]
        origin = f" (nom pris à la pharmacie OSM {row['osm_poi_id']})" if row["osm_poi_id"] else ""
        print(f"- {poi['name']}{origin} | FINESS {row['finess']} « {row['nom_finess']} » | {poi['address']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Pharmacies du registre FINESS")
    parser.add_argument("--ville", action="append", help="une ville de la table cities (option répétable)")
    parser.add_argument("--toutes", action="store_true", help="toutes les villes de la table cities")
    parser.add_argument("--essai", action="store_true", help="n'écrit rien en base, affiche le résultat")
    args = parser.parse_args()
    cities = [name for _, name in get_all_city_ids()] if args.toutes else (args.ville or [])
    if not cities:
        parser.error("--ville ou --toutes")
    pharmacies = read_pharmacies()
    if pharmacies is None:
        return
    for city in cities:
        run_city_etl(city, pharmacies, dry_run=args.essai)
    hide_closed_pharmacies(pharmacies, dry_run=args.essai)


if __name__ == "__main__":
    main()
