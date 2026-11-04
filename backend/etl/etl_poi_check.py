"""
Vérifie les commerces de la base avec des sources gratuites, sans agent, et prépare la
liste de relecture. NE MODIFIE JAMAIS LA TABLE poi (voir etl/load/load_poi_checks.py).

    osm    : relit les objets OSM : fermetures, renommages, liens et saison ignorés jusqu'ici ;
    liens  : les liens déjà en base qui ne répondent plus.

Rejouable : un passage interrompu reprend où il en était (--force pour tout refaire).

UTILISATION (dans le conteneur backend, depuis /usr/src/app) :
    python -m etl.etl_poi_check --limit 20                 # un essai
    python -m etl.etl_poi_check                            # tous les commerces, trois vérifications
    python -m etl.etl_poi_check --service Boulangerie      # un seul type de lieu
    python -m etl.etl_poi_check --only osm
    python -m etl.etl_poi_check --report           # bilan et fichier storage/relecture_poi.csv
"""
import argparse
import csv
import json
import socket
from pathlib import Path
from time import sleep
from urllib.parse import urlparse

from agents.pepite_common import check_links
from etl.extract.api_osm import extract_osm_by_ids
from etl.load.load_poi_checks import checked_ids, save_check, save_signal
from services import poi_triage_service
from etl.transform.transform_osm import osm_details, osm_signals, pick_osm_element
from utils.db_utils import MySQLUtils
from utils.logger_util import LoggerUtil

logger = LoggerUtil.get_logger("etl_poi_check")

# Les lieux qui ont un exploitant, pour qui un lien ou une fermeture ont un sens.
SERVICES = ("Restaurant", "Café", "Boulangerie", "Pharmacie", "Supérette", "Supermarché", "Station-service", "Laverie")
SOCIAL_DOMAINS = ("facebook.com", "instagram.com")
DNS_RETRY_SECONDS = 3
REPORT_PATH = Path(__file__).resolve().parents[2] / "storage" / "relecture_poi.csv"


def load_pois(services: list) -> list:
    """Un lieu classé dans deux services n'est vérifié qu'une fois, avec le premier des services demandés."""
    connection = MySQLUtils.connect()
    cursor = connection.cursor(dictionary=True)
    marks = ",".join(["%s"] * len(services))
    cursor.execute(
        f"""SELECT p.id, p.name, p.url, p.address, p.latitude, p.longitude, p.original_id, s.name AS source_name,
                   sv.name AS service
            FROM poi p
            JOIN poi_service ps ON ps.poi_id = p.id
            JOIN services sv ON sv.id = ps.service_id AND sv.name IN ({marks})
            JOIN sources s ON s.id = p.source_id
            ORDER BY p.id""", services)
    rows = {}
    for row in cursor.fetchall():
        known = rows.get(row["id"])
        if not known or services.index(row["service"]) < services.index(known["service"]):
            rows[row["id"]] = row
    cursor.close()
    MySQLUtils.disconnect(connection)
    return list(rows.values())


def write_results(results: list) -> None:
    """results : (poi_id, source, bilan, [(signal, détail)...]). Une transaction par paquet, sans garder la connexion."""
    connection = MySQLUtils.connect()
    cursor = connection.cursor()
    for poi_id, source, result, signals in results:
        save_check(cursor, poi_id, source, result)
        for signal_type, detail in signals:
            save_signal(cursor, poi_id, source, signal_type, detail)
    connection.commit()
    cursor.close()
    MySQLUtils.disconnect(connection)


def check_osm(rows: list, force: bool, limit: int | None) -> None:
    done = set() if force else checked_ids("osm")
    todo = [row for row in rows if row["source_name"] == "osm" and row["id"] not in done
            and (row["original_id"] or "").isdigit()][:limit]
    logger.info(f"[osm] {len(todo)} lieu(x) à relire")
    elements, unread = extract_osm_by_ids(sorted({row["original_id"] for row in todo}))
    if unread:
        # Un objet non lu ne prouve rien : on ne conclut pas sur lui, le prochain passage le reprendra.
        logger.warning(f"[osm] {len(unread)} identifiant(s) non lus, à relancer")
    results = []
    for row in todo:
        if row["original_id"] in unread:
            continue
        element = pick_osm_element(elements.get(row["original_id"], []), row["latitude"], row["longitude"])
        details = osm_details(element.get("tags", {})) if element else {}
        result = {**details, "present": bool(element), "type_osm": element["type"] if element else None}
        results.append((row["id"], "osm", result, osm_signals(row, element)))
    write_results(results)
    logger.info(f"[osm] {len(results)} relu(s), {sum(len(item[3]) for item in results)} signal(aux)")


def absolute_url(url: str) -> str:
    return url if url.startswith(("http://", "https://")) else f"https://{url}"


def is_social(url: str) -> bool:
    return any(domain in urlparse(url).netloc.lower() for domain in SOCIAL_DOMAINS)


def domain_exists(url: str) -> bool:
    """check_links ne distingue pas un domaine disparu d'un site en panne : 78 liens sur 540 dans ce cas au pilote."""
    host = urlparse(url).hostname
    if not host:
        return False
    for attempt in range(2):
        try:
            socket.getaddrinfo(host, None)
            return True
        except socket.gaierror:
            if attempt == 0:
                sleep(DNS_RETRY_SECONDS)
    return False


def check_dead_links(rows: list, limit: int | None) -> None:
    """Facebook et Instagram sont ignorés : ils refusent le code, sans dire si la page existe."""
    links = {row["id"]: absolute_url(row["url"].strip()) for row in rows if (row["url"] or "").strip()}
    links = {poi_id: url for poi_id, url in list(links.items())[:limit] if not is_social(url)}
    statuses = check_links(set(links.values()))
    results = []
    for poi_id, url in links.items():
        status = statuses[url]
        if status is False:
            results.append((poi_id, "liens", {"statut": "mort"}, [("lien_mort", {"url": url, "raison": "404 ou 410"})]))
        elif status is None and not domain_exists(url):
            results.append((poi_id, "liens", {"statut": "mort"}, [("lien_mort", {"url": url, "raison": "domaine introuvable"})]))
        else:
            results.append((poi_id, "liens", {"statut": "repond" if status else "incertain"}, []))
    write_results(results)
    logger.info(f"[liens] {len(results)} vérifié(s), {sum(1 for item in results if item[3])} mort(s)")


def report() -> None:
    connection = MySQLUtils.connect()
    cursor = connection.cursor(dictionary=True)
    cursor.execute(
        """SELECT sg.signal_type, sg.source, p.id, p.name, p.address, p.url, sg.statut, sg.detail,
                  (SELECT MIN(sv.name) FROM poi_service ps JOIN services sv ON sv.id = ps.service_id
                   WHERE ps.poi_id = p.id) AS service
           FROM poi_signals sg JOIN poi p ON p.id = sg.poi_id
           ORDER BY sg.signal_type, service, p.name""")
    rows = cursor.fetchall()
    cursor.close()
    MySQLUtils.disconnect(connection)
    counts = {}
    for row in rows:
        counts[row["signal_type"]] = counts.get(row["signal_type"], 0) + 1
    for signal_type, count in sorted(counts.items()):
        print(f"{count:>5}  {signal_type}")
    with open(REPORT_PATH, "w", newline="", encoding="utf-8-sig") as file:
        writer = csv.writer(file, delimiter=";")
        writer.writerow(["signal", "source", "service", "poi_id", "nom", "adresse", "lien_actuel", "statut", "detail"])
        for row in rows:
            detail = row["detail"] if isinstance(row["detail"], str) else json.dumps(row["detail"], ensure_ascii=False)
            writer.writerow([row["signal_type"], row["source"], row["service"], row["id"], row["name"], row["address"], row["url"],
                             row["statut"], detail])
    print(f"{len(rows)} ligne(s) dans {REPORT_PATH}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", choices=("osm", "liens"), help="Une seule vérification")
    parser.add_argument("--limit", type=int, help="Nombre de lieux par vérification (pour un essai)")
    parser.add_argument("--service", action="append", choices=list(SERVICES),
                        help="Type de lieu (répétable ; par défaut tous)")
    parser.add_argument("--force", action="store_true", help="Refaire aussi ce qui a déjà été vérifié")
    parser.add_argument("--report", action="store_true", help="Bilan et fichier de relecture, sans rien vérifier")
    args = parser.parse_args()

    if args.report:
        report()
        return
    rows = load_pois(args.service or list(SERVICES))
    if args.only in (None, "osm"):
        check_osm(rows, args.force, args.limit)
    if args.only in (None, "liens"):
        check_dead_links(rows, args.limit)
    poi_triage_service.run()


if __name__ == "__main__":
    main()
