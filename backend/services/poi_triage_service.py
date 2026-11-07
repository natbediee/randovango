"""
Le tri automatique des signaux sur les services : réserver à l'humain ce qui demande un jugement.

    appliqué : liens morts retirés, liens contrôlés ajoutés, sous le nom RULE_AUTHOR. Annulable ;
               fermeture signalée sans autre nom : lieu retiré (OSM fermé ou absent, ou fermeture définitive lue par
               l'agent), sauf un restaurant que l'agent des restaurants a trouvé ouvert depuis (il a sa fiche) ;
               lien OSM vers une page qui n'existe plus : refusé ;
    sans suite : ce que l'agent des restaurants a rendu inutile (7 novembre 2026, 540 lieux sur les 900 à relire).
               Un restaurant sans fiche dans une commune traitée n'est plus montré au voyageur (step4.py) : ses
               liens, saisons et fermetures ne servent plus. Un restaurant avec fiche a déjà son lien et sa saison,
               contrôlés par cet agent ; ses fermetures restent à relire, car les deux sources se contredisent ;
    à relire : tout le reste.

DANS LE DOUTE ON N'AFFICHE PAS (must_hide) : une fermeture signalée masque le lieu au voyageur, comme un
spot proposé au retrait. « Garder tel quel » le remet. Une décision humaine prime : ses signaux ne sont plus
relus ici, et une décision annulée n'est pas reprise par la règle.

UTILISATION (dans le conteneur backend, depuis /usr/src/app) :
    python -m services.poi_triage_service --essai   # compte, n'écrit rien
    python -m services.poi_triage_service
"""
import argparse
import json
import re
from concurrent.futures import ThreadPoolExecutor

from agents.find_service_links import commune_of, control_page, read_page
from services import poi_review_service as review
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


def _control_osm_link(signal: dict) -> str:
    """Le contrôle de l'agent, appliqué à un lien posé par un contributeur."""
    url = review.signal_detail(signal).get("url") or ""
    if any(domain in url for domain in SOCIAL_DOMAINS):
        return "a_valider_social"
    commune, postcode = commune_of(signal["address"])
    if not commune:
        return "sans_commune"
    place = {"name": signal["name"], "commune": commune, "cp": postcode, "telephone": signal["telephone"]}
    return control_page({"url": url, "type_page": "site"}, read_page(url), place)["verdict"]


def _control_new_osm_links(cursor, signals: list) -> None:
    """Une seule fois par lien : le verdict reste dans le signal, et s'affiche sur la fiche."""
    todo = [signal for signal in signals if signal["signal_type"] == "lien_osm"
            and not review.signal_detail(signal).get("controle")]
    with ThreadPoolExecutor(max_workers=READ_WORKERS) as pool:
        verdicts = list(pool.map(_control_osm_link, todo))
    for signal, verdict in zip(todo, verdicts):
        detail = {**review.signal_detail(signal), "controle": verdict}
        signal["detail"] = json.dumps(detail, ensure_ascii=False)
        cursor.execute("UPDATE poi_signals SET detail = %s WHERE id = %s", (signal["detail"], signal["id"]))


def must_remove(signals: list) -> bool:
    """Une fermeture signalée sans autre nom : ni renommage, ni reprise, ni fermeture du moment."""
    if review.new_name_of(signals) or any(signal["signal_type"] == "renommage_osm" for signal in signals):
        return False
    return any(signal["signal_type"] in CLOSED_SIGNALS for signal in signals) or any(
        signal["signal_type"] == "fermeture_agent" and review.signal_detail(signal).get("type") == "definitive" for signal in signals)


def postcode_of(address: str | None) -> str | None:
    found = re.search(r"\b\d{5}\b", address or "")
    return found.group(0) if found else None


def _restaurants(cursor) -> tuple:
    """(restaurants qui ont une fiche, codes postaux des communes traitées par l'agent des restaurants)."""
    cursor.execute("SELECT p.id, p.address FROM poi p JOIN restaurants r ON r.poi_id = p.id")
    rows = cursor.fetchall()
    cursor.execute("""
        SELECT DISTINCT ps.poi_id FROM poi_service ps JOIN services s ON s.id = ps.service_id WHERE s.category = %s
    """, (RESTAURANT,))
    restaurant_ids = {row["poi_id"] for row in cursor.fetchall()}
    return {row["id"] for row in rows}, {postcode_of(row["address"]) for row in rows} - {None}, restaurant_ids


def without_follow_up(tab: str, poi: dict, with_sheet: set, treated: set, restaurant_ids: set) -> bool:
    """Ce signal n'apporte plus rien : l'agent des restaurants est passé après lui."""
    if poi["poi_id"] not in restaurant_ids:
        return False
    if poi["poi_id"] in with_sheet:
        return tab in ("liens", "saison")
    return postcode_of(poi["address"]) in treated


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
               "a_relire": 0, "lieux_masques": 0}
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
        with_sheet, treated, restaurant_ids = _restaurants(cursor)

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
                elif without_follow_up("fermetures", poi, with_sheet, treated, restaurant_ids):
                    review.decide_one(cursor, "fermetures", poi_id, "sans_suite", "", RULE_AUTHOR, None)
                    summary["sans_suite"] += 1
                    closures = []
            if closures:
                summary["a_relire"] += 1
            if "saison" in tabs and (poi_id, "saison") not in cancelled \
                    and without_follow_up("saison", poi, with_sheet, treated, restaurant_ids):
                review.decide_one(cursor, "saison", poi_id, "sans_suite", "", RULE_AUTHOR, None)
                summary["sans_suite"] += 1
            if any(s["signal_type"] == "lien_mort" for s in poi_signals) and (poi_id, "morts") not in cancelled:
                review.decide_one(cursor, "morts", poi_id, "retirer_lien", "", RULE_AUTHOR, None)
                summary["liens_retires"] += 1
            links = [s for s in poi_signals if review.SIGNAL_TAB.get(s["signal_type"]) == "liens"]
            # Une fermeture signalée bloque le lien : un site peut survivre à son restaurant (Mary Stuart).
            if links and (poi_id, "liens") not in cancelled:
                if without_follow_up("liens", poi, with_sheet, treated, restaurant_ids):
                    review.decide_one(cursor, "liens", poi_id, "sans_suite", "", RULE_AUTHOR, None)
                    summary["sans_suite"] += 1
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
