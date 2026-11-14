"""
Le bilan de la supervision : combien il reste à trancher, file par file.

Il compte aussi les notes données aux propositions des agents (count_ratings, carte #201), pour vérifier que la
notation sert au jeu d'évaluation (#114).

Les chiffres sont comptés avec les règles mêmes des pages Spots et Services
(supervision_service.spot_status, poi_review_service._pending) : le bilan ne peut pas
annoncer ce que ces pages ne montreraient pas. Un lieu présent dans deux files compte
une fois dans chacune, comme le filtre « Problème » de la page Services, dont « Tous » fait la somme.
"""
from collections import Counter

from services import decision_rating, poi_review_service, supervision_service
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

# Les catégories des notes : les spots, puis les onglets de l'étape 4 (poi_review_service.step4_tab), avec les libellés
# du filtre « Type » de la page Services (SERVICE_TABS dans supervision_services.js).
RATING_CATEGORIES = {
    "spot": "Spots", "eau": "Eau", "vidange": "Vidange", "gasoil": "Carburant", "supermarche": "Supermarché",
    "commerce": "Commerce", "restauration": "Restauration", "cafe": "Café, bar", "toilettes": "Toilettes",
    "hygiene": "Hygiène", "laverie": "Laverie", "culture": "Culture & Loisirs", "urgence": "Urgences",
    "hors_etape4": "Hors étape 4",
}

# Les décisions notées et encore valables, avec la catégorie de leur lieu : un spot, ou le service d'un lieu.
RATED_DECISIONS = """
    SELECT d.objet_type, d.pertinence, d.raison,
           (SELECT MIN(s.category) FROM poi_service ps JOIN services s ON s.id = ps.service_id
            WHERE d.objet_type = %s AND ps.poi_id = d.objet_id) AS service_category
    FROM decisions d
    WHERE d.pertinence IS NOT NULL AND d.annulee_at IS NULL AND d.objet_type IN (%s, %s)
"""


def count_spots(states: dict) -> dict:
    """{statut: nombre} pour les spots qui ont une vérification ou une décision."""
    statuses = Counter(supervision_service.spot_status(verification, decision)
                       for verification, decision in states.values())
    return {"a_relire": statuses["propose"], "gardes": statuses["garde"], "retires": statuses["retire"]}


def ranked(counter: Counter) -> list:
    """[{label, n}], du plus chargé au moins chargé, puis par ordre alphabétique."""
    return [{"label": label, "n": n} for label, n in sorted(counter.items(), key=lambda item: (-item[1], item[0]))]


def rating_category(row: dict) -> str:
    """La catégorie d'une décision notée : « spot », ou l'onglet de l'étape 4 du lieu (« restauration »)."""
    if row["objet_type"] == supervision_service.SPOT:
        return "spot"
    return poi_review_service.step4_tab(row.get("service_category"))


def count_ratings(rows: list) -> list:
    """
    Les notes des propositions, par catégorie : [{label, n, pertinences: [{label, n}], raisons: [{label, n}]}].
    Les trois pertinences sont toujours là, dans l'ordre (0 si aucune), les raisons de la plus fréquente à la plus rare.
    Les catégories viennent dans l'ordre de RATING_CATEGORIES ; celles sans note n'apparaissent pas.
    """
    by_category = {}
    for row in rows:
        by_category.setdefault(rating_category(row), []).append(row)
    counts = []
    for category, label in RATING_CATEGORIES.items():
        rated = by_category.get(category)
        if not rated:
            continue
        pertinences = Counter(row["pertinence"] for row in rated)
        reasons = Counter(decision_rating.RAISONS.get(row["raison"], row["raison"]) for row in rated if row["raison"])
        counts.append({
            "label": label,
            "n": len(rated),
            "pertinences": [{"label": name, "n": pertinences[value]} for value, name in decision_rating.PERTINENCES.items()],
            "raisons": ranked(reasons),
        })
    return counts


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
    """Le bilan lu en base : ce qui reste à trancher, file par file, et le compte des notes des propositions."""
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
        # Le service n'est cherché que pour un lieu (poi) : un numéro de spot n'est pas un numéro de lieu.
        cursor.execute(RATED_DECISIONS, (poi_review_service.POI, supervision_service.SPOT, poi_review_service.POI))
        ratings = count_ratings(cursor.fetchall())
        cursor.close()
        return {**summarize(states, spot_cities, groups, pois, openings, decisions), "notation": ratings}
    finally:
        MySQLUtils.disconnect(connection)
