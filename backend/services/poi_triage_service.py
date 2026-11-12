"""
Le tri automatique des signaux sur les services : réserver à l'humain ce qui demande un jugement.

    appliqué : liens morts retirés, liens contrôlés ajoutés, sous le nom RULE_AUTHOR. Annulable ;
               fermeture signalée sans autre nom : lieu retiré (OSM fermé ou absent, ou fermeture définitive lue par
               l'agent), sauf un restaurant que l'agent des restaurants a trouvé ouvert depuis (il a sa fiche) ;
               lien OSM vers une page qui n'existe plus : refusé ;
               lien OSM déjà jugé mort ou refusé, ou dont le domaine n'existe plus : refusé (8 novembre 2026, « Au jardin »
               à Marseille revenait par OSM après le retrait de son lien mort) ;
    sans suite : ce que les agents des restaurants et des commerces ont rendu inutile (7 novembre 2026, 540 lieux sur
               les 900 à relire ; commerces et cafés le 8 novembre). Un lieu sans fiche dans une commune traitée par
               l'agent de son onglet n'est plus montré au voyageur (step4.py) : ses liens, saisons, renommages et
               fermetures ne servent plus. Un lieu avec fiche a déjà son lien et sa saison, contrôlés par l'agent ;
               ses fermetures restent à relire, car les deux sources se contredisent ;
    à relire : tout le reste.

DANS LE DOUTE ON N'AFFICHE PAS (must_hide) : une fermeture signalée masque le lieu au voyageur, comme un
spot proposé au retrait. « Garder tel quel » le remet. Une décision humaine prime : ses signaux ne sont plus
relus ici, et une décision annulée n'est pas reprise par la règle.

LES STATIONS-SERVICE DOUTEUSES (hide_doubtful_stations, carte #180) : une station de l'État avec un signal des
carburants à relire (etl/transform/transform_carburants.py) est masquée. Quand ses signaux n'ont plus lieu d'être (elle
déclare de nouveau, elle revient dans le fichier), le chargement les efface et elle est réaffichée sans relecture,
sauf si un humain l'a retirée ou fusionnée. Appelée à la fin de chaque passage de etl/etl_carburants.py.

UTILISATION (dans le conteneur backend, depuis /usr/src/app) :
    python -m services.poi_triage_service --essai   # compte, n'écrit rien
    python -m services.poi_triage_service
"""
import argparse
import json
import re
import socket
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

from agents.find_service_links import commune_of, control_page, read_page
from services import poi_review_service as review
from services.commerce_selection_service import COMMERCE_SERVICES, OWN_TAB
from etl.load.load_carburants import REMOVING_DECISIONS, SIGNALS_FROM_OSM, SIGNALS_FROM_STATE
from etl.load.load_carburants import SOURCE_NAME as FUEL_SOURCE
from utils.db_utils import MySQLUtils
from utils.logger_util import LoggerUtil

logger = LoggerUtil.get_logger("etl_poi_check")

RULE_AUTHOR = "règle automatique"
AUTO_LINK_TYPES = ("site", "office_tourisme")
SOCIAL_DOMAINS = ("facebook.com", "instagram.com")
OSM_LINK_ACCEPTED = ("ok", "ok_telephone", "a_valider_social")
READ_WORKERS = 8
RESTAURANT = "restaurant"
CLOSED_SIGNALS = ("fermeture_osm", "absent_osm")


def must_hide(signals: list) -> bool:
    """Une fermeture signalée. Pas un renommage, le lieu existe. Ni une fermeture du moment."""
    if {signal["signal_type"] for signal in signals} & {"fermeture_osm", "absent_osm"}:
        return True
    return any(signal["signal_type"] == "fermeture_agent" and review.signal_detail(signal).get("type") in ("definitive", "reprise")
               for signal in signals)


def auto_link_allowed(signals: list) -> bool:
    """
    Un lien de l'agent contrôlé par le code, sur un site ou une fiche, ou un lien OSM qui a passé le même
    contrôle. Un réseau social d'OSM est accepté sans lecture : le code ne peut pas le lire, mais un
    contributeur l'a rattaché à cet objet précis, donc peu de risque d'homonyme (décision du 2026-11-02).
    """
    agent = next((s for s in signals if s["signal_type"] == "lien_agent"), None)
    if agent:
        detail = review.signal_detail(agent)
        return detail.get("niveau") == "auto" and detail.get("type_page") in AUTO_LINK_TYPES
    osm = next((s for s in signals if s["signal_type"] == "lien_osm"), None)
    return bool(osm) and review.signal_detail(osm).get("controle") in OSM_LINK_ACCEPTED


def domain_exists(url: str) -> bool:
    """Le nom du site répond-il encore ? Un domaine qui n'existe plus est un lien mort, pas une page illisible."""
    host = urlparse(url if "://" in url else f"http://{url}").hostname
    try:
        return bool(host) and bool(socket.getaddrinfo(host, None))
    except (socket.gaierror, UnicodeError):
        return False


def link_key(url: str | None) -> str:
    """Un lien sans http, www ni barre finale : « http://aujardin-marseille.com » et « https://www.aujardin-marseille.com/ »."""
    url = (url or "").strip().lower()
    url = re.sub(r"^https?://", "", url)
    return re.sub(r"^www\.", "", url).rstrip("/")


def _control_osm_link(signal: dict) -> str:
    """Le contrôle de l'agent, appliqué à un lien posé par un contributeur."""
    url = review.signal_detail(signal).get("url") or ""
    if any(domain in url for domain in SOCIAL_DOMAINS):
        return "a_valider_social"
    if not domain_exists(url):
        return "lien_mort"
    commune, postcode = commune_of(signal["address"])
    if not commune:
        return "sans_commune"
    place = {"name": signal["name"], "commune": commune, "cp": postcode, "telephone": signal["telephone"]}
    return control_page({"url": url, "type_page": "site"}, read_page(url), place)["verdict"]


def _control_new_osm_links(cursor, signals: list) -> None:
    """Une seule fois par lien : le verdict reste dans le signal, et s'affiche sur la fiche."""
    # Une page jugée illisible avant le 8 novembre 2026 est recontrôlée une fois : son domaine a pu disparaître.
    todo = [signal for signal in signals if signal["signal_type"] == "lien_osm"
            and (not review.signal_detail(signal).get("controle")
                 or (review.signal_detail(signal).get("controle") == "page_illisible"
                     and not review.signal_detail(signal).get("domaine_verifie")))]
    with ThreadPoolExecutor(max_workers=READ_WORKERS) as pool:
        verdicts = list(pool.map(_control_osm_link, todo))
    for signal, verdict in zip(todo, verdicts):
        detail = {**review.signal_detail(signal), "controle": verdict, "domaine_verifie": True}
        signal["detail"] = json.dumps(detail, ensure_ascii=False)
        cursor.execute("UPDATE poi_signals SET detail = %s WHERE id = %s", (signal["detail"], signal["id"]))


def hide_doubtful_stations(trial: bool = False) -> dict:
    """
    Masque les stations de l'État qui ont un signal des carburants à relire ; réaffiche celles qui n'ont plus rien à
    relire et qu'aucune décision non annulée n'a retirées ou fusionnées. Renvoie {"masquees": n, "reaffichees": n}.
    """
    sources = (SIGNALS_FROM_OSM, SIGNALS_FROM_STATE)
    removing = ", ".join(["%s"] * len(REMOVING_DECISIONS))
    connection = MySQLUtils.connect()
    try:
        cursor = connection.cursor()
        cursor.execute("""
            UPDATE poi p SET p.masque = 1
            WHERE p.masque = 0 AND EXISTS (SELECT 1 FROM poi_signals sg WHERE sg.poi_id = p.id
                                           AND sg.statut = 'a_relire' AND sg.source IN (%s, %s))
        """, sources)
        hidden = cursor.rowcount
        cursor.execute(f"""
            UPDATE poi p JOIN sources s ON s.id = p.source_id SET p.masque = 0
            WHERE s.name = %s AND p.masque = 1
              AND NOT EXISTS (SELECT 1 FROM poi_signals sg WHERE sg.poi_id = p.id AND sg.statut = 'a_relire')
              AND NOT EXISTS (SELECT 1 FROM decisions d WHERE d.objet_type = %s AND d.objet_id = p.id
                              AND d.annulee_at IS NULL AND d.decision IN ({removing}))
        """, (FUEL_SOURCE, review.POI, *REMOVING_DECISIONS))
        shown = cursor.rowcount
        if trial:
            connection.rollback()
        else:
            connection.commit()
        cursor.close()
    finally:
        MySQLUtils.disconnect(connection)
    summary = {"masquees": hidden, "reaffichees": shown}
    if hidden or shown:
        logger.info(f"[tri] stations douteuses{' (essai, rien écrit)' if trial else ''} : {summary}")
    return summary


def must_remove(signals: list) -> bool:
    """Une fermeture signalée sans autre nom : ni renommage, ni reprise, ni fermeture du moment."""
    if review.new_name_of(signals) or any(signal["signal_type"] == "renommage_osm" for signal in signals):
        return False
    return any(signal["signal_type"] in CLOSED_SIGNALS for signal in signals) or any(
        signal["signal_type"] == "fermeture_agent" and review.signal_detail(signal).get("type") == "definitive" for signal in signals)


def postcode_of(address: str | None) -> str | None:
    found = re.search(r"\b\d{5}\b", address or "")
    return found.group(0) if found else None


# Les chaînes d'agents, comme à l'étape 4 (step4.keep_checked) : leurs services, et les fiches qui les prouvent.
# Les fiches de la table commerces qui ont leur onglet (cafés, supermarchés) font chacune une chaîne, avec leurs seules fiches.
SHOP_SHEETS = "SELECT p.id, p.address FROM poi p JOIN commerces c ON c.poi_id = p.id WHERE c.categorie"
OWN_TAB_SHEETS = ", ".join(f"'{sheet}'" for sheet in OWN_TAB)
CHAINS = (
    ((RESTAURANT,), "SELECT p.id, p.address FROM poi p JOIN restaurants r ON r.poi_id = p.id"),
    (COMMERCE_SERVICES, f"{SHOP_SHEETS} NOT IN ({OWN_TAB_SHEETS})"),
    *((services, f"{SHOP_SHEETS} = '{sheet}'") for sheet, services in OWN_TAB.items()),
)


def _chains(cursor) -> tuple:
    """
    ([(services, lieux qui ont une fiche, codes postaux des communes traitées)] pour chaque agent,
     {lieu: ses services}).
    """
    chains = []
    for services, sql in CHAINS:
        cursor.execute(sql)
        rows = cursor.fetchall()
        chains.append((set(services), {row["id"] for row in rows}, {postcode_of(row["address"]) for row in rows} - {None}))
    cursor.execute("SELECT ps.poi_id, s.category FROM poi_service ps JOIN services s ON s.id = ps.service_id")
    categories = {}
    for row in cursor.fetchall():
        categories.setdefault(row["poi_id"], set()).add(row["category"])
    return chains, categories


def _clear_unproved_badges(cursor, chains: list, categories: dict) -> int:
    """
    « Vérifié » suit la preuve dans les onglets des agents (service_store.set_verified) : une ligne d'OSM sans
    fiche n'a été contrôlée par personne, même chargée avec verifie = 1 (load_poi.py). L'étape 4 le cachait déjà
    (step4.shown_verified) ; la supervision lit la base, elle montrait « Vérifié » (8 novembre 2026, « Au jardin »).
    """
    services = set().union(*(chain_services for chain_services, _, _ in chains))
    sheets = set().union(*(with_sheet for _, with_sheet, _ in chains))
    ids = [poi_id for poi_id, poi_categories in categories.items() if poi_categories & services and poi_id not in sheets]
    if not ids:
        return 0
    marks = ", ".join(["%s"] * len(ids))
    cursor.execute(f"UPDATE poi SET verifie = 0 WHERE verifie = 1 AND id IN ({marks})", tuple(ids))
    return cursor.rowcount


def without_follow_up(tab: str, poi: dict, chains: list, categories: dict) -> bool:
    """Ce signal n'apporte plus rien : l'agent de l'onglet du lieu est passé après lui."""
    for services, with_sheet, treated in chains:
        if not categories.get(poi["poi_id"], set()) & services:
            continue
        if poi["poi_id"] in with_sheet:
            return tab in ("liens", "saison")
        return postcode_of(poi["address"]) in treated
    return False


def _judged_links(cursor) -> set:
    """
    (lieu, lien) déjà refusés ou retirés comme morts, par un humain ou la règle : OSM ne doit pas les reproposer.
    Une décision annulée ne compte pas.
    """
    cursor.execute("""SELECT objet_id, detail FROM decisions WHERE objet_type = %s AND annulee_at IS NULL
                      AND decision IN ('refuser_lien', 'retirer_lien')""", (review.POI,))
    judged, signal_ids = set(), {}
    for row in cursor.fetchall():
        detail = review.signal_detail(row)
        if (detail.get("avant") or {}).get("url"):
            judged.add((row["objet_id"], link_key(detail["avant"]["url"])))
        for signal_id in detail.get("signal_ids") or []:
            signal_ids[signal_id] = row["objet_id"]
    if signal_ids:
        marks = ", ".join(["%s"] * len(signal_ids))
        cursor.execute(f"SELECT id, detail FROM poi_signals WHERE id IN ({marks})", tuple(signal_ids))
        for row in cursor.fetchall():
            url = review.signal_detail(row).get("url")
            if url:
                judged.add((signal_ids[row["id"]], link_key(url)))
    return judged


def already_judged(links: list, poi_id: int, judged: set) -> bool:
    """Tous les liens proposés par OSM ont déjà été refusés ou retirés sur ce lieu."""
    return bool(links) and all(signal["signal_type"] == "lien_osm"
                               and (poi_id, link_key(review.signal_detail(signal).get("url"))) in judged for signal in links)


def _cancelled_by_human(cursor) -> set:
    """(lieu, file) dont une décision a été annulée : la règle ne la reprend pas, et ça revient à l'humain."""
    cursor.execute("SELECT objet_id, detail FROM decisions WHERE objet_type = %s AND annulee_at IS NOT NULL", (review.POI,))
    cancelled = set()
    for row in cursor.fetchall():
        detail = json.loads(row["detail"]) if isinstance(row["detail"], str) else (row["detail"] or {})
        cancelled.add((row["objet_id"], detail.get("file")))
    return cancelled


def run(trial: bool = False) -> dict:
    """Trie tous les signaux en attente. Rejouable : le résultat ne dépend que des signaux présents. À blanc, rien n'est écrit."""
    connection = MySQLUtils.connect()
    summary = {"liens_ajoutes": 0, "liens_retires": 0, "liens_refuses": 0, "lieux_retires": 0, "sans_suite": 0,
               "a_relire": 0, "lieux_masques": 0, "badges_retires": 0}
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("""
            SELECT sg.id, sg.poi_id, sg.source, sg.signal_type, sg.detail, sg.statut, p.name, p.address, p.masque,
                   osm.result->>'$.phone' AS telephone
            FROM poi_signals sg JOIN poi p ON p.id = sg.poi_id
            LEFT JOIN poi_checks osm ON osm.poi_id = p.id AND osm.source = 'osm'
            WHERE sg.statut = 'a_relire'
        """)
        signals = [{**row, "telephone": None if row["telephone"] in (None, "null") else row["telephone"]}
                   for row in cursor.fetchall()]
        if not trial:
            _control_new_osm_links(cursor, signals)
            connection.commit()
        cancelled = _cancelled_by_human(cursor)
        chains, categories = _chains(cursor)
        with_sheet = set().union(*(sheets for _, sheets, _ in chains))
        judged = _judged_links(cursor)
        summary["badges_retires"] = _clear_unproved_badges(cursor, chains, categories)

        by_poi = {}
        for signal in signals:
            by_poi.setdefault(signal["poi_id"], []).append(signal)
        for poi_id, poi_signals in by_poi.items():
            poi = poi_signals[0]
            tabs = {review.SIGNAL_TAB.get(s["signal_type"]) for s in poi_signals}
            closures = [s for s in poi_signals if review.SIGNAL_TAB.get(s["signal_type"]) == "fermetures"]
            hide = bool(closures) and must_hide(closures)
            if hide and not poi["masque"]:
                cursor.execute("UPDATE poi SET masque = 1 WHERE id = %s", (poi_id,))
                summary["lieux_masques"] += 1
            if closures and (poi_id, "fermetures") not in cancelled:
                if must_remove(closures) and poi_id not in with_sheet:
                    review.decide_one(cursor, "fermetures", poi_id, "retirer", "", RULE_AUTHOR, None)
                    summary["lieux_retires"] += 1
                    closures = []
                elif without_follow_up("fermetures", poi, chains, categories):
                    review.decide_one(cursor, "fermetures", poi_id, "sans_suite", "", RULE_AUTHOR, None)
                    summary["sans_suite"] += 1
                    closures = []
            if closures:
                summary["a_relire"] += 1
            if "saison" in tabs and (poi_id, "saison") not in cancelled \
                    and without_follow_up("saison", poi, chains, categories):
                review.decide_one(cursor, "saison", poi_id, "sans_suite", "", RULE_AUTHOR, None)
                summary["sans_suite"] += 1
            if any(s["signal_type"] == "lien_mort" for s in poi_signals) and (poi_id, "morts") not in cancelled:
                review.decide_one(cursor, "morts", poi_id, "retirer_lien", "", RULE_AUTHOR, None)
                summary["liens_retires"] += 1
            links = [s for s in poi_signals if review.SIGNAL_TAB.get(s["signal_type"]) == "liens"]
            # Une fermeture signalée bloque le lien : un site peut survivre à son restaurant (Mary Stuart).
            if links and (poi_id, "liens") not in cancelled:
                if without_follow_up("liens", poi, chains, categories):
                    review.decide_one(cursor, "liens", poi_id, "sans_suite", "", RULE_AUTHOR, None)
                    summary["sans_suite"] += 1
                elif already_judged(links, poi_id, judged):
                    review.decide_one(cursor, "liens", poi_id, "refuser_lien", "", RULE_AUTHOR, None)
                    summary["liens_refuses"] += 1
                elif not hide and auto_link_allowed(links):
                    review.decide_one(cursor, "liens", poi_id, "valider_lien", "", RULE_AUTHOR, None)
                    summary["liens_ajoutes"] += 1
                elif all(s["signal_type"] == "lien_osm" and review.signal_detail(s).get("controle") == "lien_mort" for s in links):
                    review.decide_one(cursor, "liens", poi_id, "refuser_lien", "", RULE_AUTHOR, None)
                    summary["liens_refuses"] += 1
            if not trial:
                connection.commit()
        if trial:
            connection.rollback()
        cursor.close()
    finally:
        MySQLUtils.disconnect(connection)
    logger.info(f"[tri] {'essai, rien écrit : ' if trial else ''}{summary}")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--essai", action="store_true", help="Compte ce que la règle trancherait, n'écrit rien")
    print(run(parser.parse_args().essai))
