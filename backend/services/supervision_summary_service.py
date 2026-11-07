"""
Le bilan de la supervision : combien il reste à trancher, file par file.

Les chiffres sont comptés avec les règles mêmes des pages Spots et Services
(supervision_service.spot_status, poi_review_service._pending) : le bilan ne peut pas
annoncer ce que ces pages ne montreraient pas. Un lieu présent dans deux files compte
une fois dans chacune, comme le filtre « Problème » de la page Services, dont « Tous » fait la somme.
"""
from collections import Counter

from services import poi_review_service, supervision_service
from utils.db_utils import MySQLUtils

# Les files des services (poi_review_service.TAB_SIGNALS), avec le libellé et l'ordre du filtre
# « Problème » de la page Services (TABS dans supervision_services.js).
SERVICE_TABS = {
    "fermetures": "Doute sur le nom",
    "liens": "Liens",
    "saison": "Saison",
    "doublons": "Doublons",
    "confirmer": "À confirmer",
}
NO_CITY = "Ville inconnue"
NO_TYPE = "Type inconnu"


def count_spots(states: dict) -> dict:
    """{statut: nombre} pour les spots qui ont une vérification ou une décision."""
    statuses = Counter(supervision_service.spot_status(verification, decision)
                       for verification, decision in states.values())
    return {"a_relire": statuses["propose"], "gardes": statuses["garde"], "retires": statuses["retire"]}


def ranked(counter: Counter) -> list:
    """[{label, n}], du plus chargé au moins chargé, puis par ordre alphabétique."""
    return [{"label": label, "n": n} for label, n in sorted(counter.items(), key=lambda item: (-item[1], item[0]))]


def summarize(states: dict, spot_cities: dict, groups: dict, pois: dict, openings: int, decisions: int) -> dict:
    """Assemble le bilan à partir de ce que la base a donné (sans y toucher : testable seul)."""
    spots = count_spots(states)
    pending_spots = [spot_id for spot_id, (verification, decision) in states.items()
                     if supervision_service.spot_status(verification, decision) == "propose"]

    files = Counter(tab for tab, _ in groups)
    by_type = Counter((pois.get(poi_id) or {}).get("service") or NO_TYPE for _, poi_id in groups)
    by_city = Counter(spot_cities.get(spot_id) or NO_CITY for spot_id in pending_spots)
    by_city.update((pois.get(poi_id) or {}).get("commune") or NO_CITY for _, poi_id in groups)

    services_pending = sum(files.values())
    return {
        "total": spots["a_relire"] + services_pending,
        "decisions": decisions,
        "spots": {**spots, "ouvertures": openings},
        "services": {
            "a_relire": services_pending,
            "files": [{"tab": tab, "label": label, "n": files[tab]} for tab, label in SERVICE_TABS.items()],
            "par_type": ranked(by_type),
        },
        "par_ville": ranked(by_city),
    }


def get_summary() -> dict:
    connection = MySQLUtils.connect()
    try:
        cursor = connection.cursor(dictionary=True)
        states = supervision_service._spot_states(cursor)
        spot_labels = supervision_service._spot_labels(cursor, list(states))
        spot_cities = {spot_id: label.get("city_label") for spot_id, label in spot_labels.items()}
        groups, pois = poi_review_service._pending(cursor, None, None)
        cursor.execute("SELECT COUNT(*) AS n FROM decisions WHERE objet_type = %s AND annulee_at IS NULL",
                       (supervision_service.OPENING_OBJECT,))
        openings = cursor.fetchone()["n"]
        cursor.execute("SELECT COUNT(*) AS n FROM decisions WHERE annulee_at IS NULL")
        decisions = cursor.fetchone()["n"]
        cursor.close()
        return summarize(states, spot_cities, groups, pois, openings, decisions)
    finally:
        MySQLUtils.disconnect(connection)
