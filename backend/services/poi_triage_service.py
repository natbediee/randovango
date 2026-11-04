"""
Le tri automatique des signaux sur les services : réserver à l'humain ce qui demande un jugement.

    appliqué : liens morts retirés, liens contrôlés ajoutés, sous le nom RULE_AUTHOR. Annulable ;
    à relire : tout le reste.

DANS LE DOUTE ON N'AFFICHE PAS (must_hide) : une fermeture signalée masque le lieu au voyageur, comme un
spot proposé au retrait. « Garder tel quel » le remet. Une décision humaine prime : ses signaux ne sont plus
relus ici, et une décision annulée n'est pas reprise par la règle.

UTILISATION (dans le conteneur backend, depuis /usr/src/app) :
    python -m services.poi_triage_service
"""
import json
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


def _cancelled_by_human(cursor) -> set:
    """(lieu, file) dont une décision a été annulée : la règle ne la reprend pas, et ça revient à l'humain."""
    cursor.execute("SELECT objet_id, detail FROM decisions WHERE objet_type = %s AND annulee_at IS NOT NULL", (review.POI,))
    cancelled = set()
    for row in cursor.fetchall():
        detail = json.loads(row["detail"]) if isinstance(row["detail"], str) else (row["detail"] or {})
        cancelled.add((row["objet_id"], detail.get("file")))
    return cancelled


def run() -> dict:
    """Trie tous les signaux en attente. Rejouable : le résultat ne dépend que des signaux présents."""
    connection = MySQLUtils.connect()
    summary = {"liens_ajoutes": 0, "liens_retires": 0, "a_relire": 0, "lieux_masques": 0}
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
        _control_new_osm_links(cursor, signals)
        connection.commit()
        cancelled = _cancelled_by_human(cursor)

        by_poi = {}
        for signal in signals:
            by_poi.setdefault(signal["poi_id"], []).append(signal)
        for poi_id, poi_signals in by_poi.items():
            closures = [s for s in poi_signals if review.SIGNAL_TAB.get(s["signal_type"]) == "fermetures"]
            hide = bool(closures) and must_hide(closures)
            if closures:
                summary["a_relire"] += 1
            if hide and not poi_signals[0]["masque"]:
                cursor.execute("UPDATE poi SET masque = 1 WHERE id = %s", (poi_id,))
                summary["lieux_masques"] += 1
            if any(s["signal_type"] == "lien_mort" for s in poi_signals) and (poi_id, "morts") not in cancelled:
                review.decide_one(cursor, "morts", poi_id, "retirer_lien", "", RULE_AUTHOR, None)
                summary["liens_retires"] += 1
            links = [s for s in poi_signals if review.SIGNAL_TAB.get(s["signal_type"]) == "liens"]
            # Une fermeture signalée bloque le lien : un site peut survivre à son restaurant (Mary Stuart).
            if links and not hide and (poi_id, "liens") not in cancelled and auto_link_allowed(links):
                review.decide_one(cursor, "liens", poi_id, "valider_lien", "", RULE_AUTHOR, None)
                summary["liens_ajoutes"] += 1
            connection.commit()
        cursor.close()
    finally:
        MySQLUtils.disconnect(connection)
    logger.info(f"[tri] {summary}")
    return summary


if __name__ == "__main__":
    print(run())
