"""
Supervision : l'IA propose, un humain tranche, le code applique.

verify_spots.py propose de retirer les spots qu'il juge non utilisables, mais il se trompe
parfois (un panneau qui concerne le parking voisin, un risque d'incendie passé). La page de
Supervision, réservée aux admins, présente ses propositions avec leurs preuves.

LA DÉCISION HUMAINE PRIME
Elle est rangée dans la table `decisions` : qui, quand, quoi, pourquoi. Les agents ne
l'écrasent pas. Une décision répond à une vérification précise : si une vérification plus
récente juge encore le spot non utilisable (une interdiction signalée après la décision), le
spot revient à la relecture.

CE QUE VOIT LE VOYAGEUR (is_hidden)
Dans le doute, on retire : un spot proposé au retrait est masqué dès la proposition, et
réapparaît s'il est gardé, ou si le voyage tombe après sa réouverture annoncée.

LES DATES D'OUVERTURE TRANCHÉES PAR UN HUMAIN (objet_type = 'ouverture')
Quand la fiche ne permet pas à read_openings de conclure, ou l'induit en erreur, un humain fixe la
lecture. Sa décision garde les dates choisies, si elles sont une convention (la fiche ne les donne
pas), le texte lu à ce moment et les valeurs d'avant, remises si on l'annule.
"""
import json
from collections import Counter
from datetime import date

from services.supervision import rating
from services.supervision.decisions import record_decision
from utils.db_utils import MySQLUtils
from utils.display_utils import HIDDEN_SPOT_TYPES, a_savoir_on, spot_category, spot_name_label
from utils.geo_utils import address_town, communes_only, town_key
from utils.paris_time import paris_date_text

DECISIONS = ("retirer", "garder")
SPOT = "spot"
OPENING_OBJECT = "ouverture"
OPENING_STATUSES = ("toute_annee", "periode", "saison", "inconnue")
RECENT_DECISIONS = 10
PROOF_REVIEWS = 5

def spot_status(verification: dict | None, decision: dict | None) -> str:
    """
    État d'un spot : "retire", "garde", "propose" (retrait à relire) ou "normal".
    Une décision de retrait vaut toujours ; une décision de garder ne vaut que pour la
    vérification à laquelle elle répond.
    """
    if decision and decision["decision"] == "retirer":
        return "retire"
    if not verification or verification["utilisable"] != "non":
        return "garde" if decision else "normal"
    if decision and decision["verification_id"] == verification["id"]:
        return "garde"
    return "propose"


def is_hidden(status: str, reopening: date | None, on_date: date) -> bool:
    """Le spot est masqué au voyageur s'il est retiré ou à relire, jusqu'à sa réouverture annoncée."""
    if status not in ("retire", "propose"):
        return False
    return reopening is None or reopening > on_date


LATEST_VERIFICATIONS = """
    SELECT v.* FROM spot_verifications v
    JOIN (SELECT spot_id, MAX(id) AS id FROM spot_verifications GROUP BY spot_id) latest ON latest.id = v.id
"""
ACTIVE_DECISIONS = """
    SELECT d.* FROM decisions d
    JOIN (SELECT objet_id, MAX(id) AS id FROM decisions
          WHERE objet_type = 'spot' AND annulee_at IS NULL GROUP BY objet_id) latest ON latest.id = d.id
"""


def _spot_states(cursor) -> dict:
    """{id du spot: (dernière vérification, décision en vigueur)}, pour les spots qui en ont une."""
    cursor.execute(LATEST_VERIFICATIONS)
    verifications = {row["spot_id"]: row for row in cursor.fetchall()}
    cursor.execute(ACTIVE_DECISIONS)
    decisions = {row["objet_id"]: row for row in cursor.fetchall()}
    return {spot_id: (verifications.get(spot_id), decisions.get(spot_id))
            for spot_id in verifications.keys() | decisions.keys()}


def hidden_spot_ids(connection, cursor, on_date: date) -> set:
    """Les spots à ne pas proposer au voyageur à cette date."""
    hidden = set()
    for spot_id, (verification, decision) in _spot_states(cursor).items():
        reopening = verification["utilisable_a_partir"] if verification else None
        if is_hidden(spot_status(verification, decision), reopening, on_date):
            hidden.add(spot_id)
    return hidden


def corrected_sentences(text: str) -> list:
    """Le texte d'un relecteur en phrases : une par ligne, les lignes vides sont ignorées."""
    return [line.strip() for line in text.splitlines() if line.strip()]


def reworked_a_savoir(cursor, spot_ids: list, on_date: date) -> dict:
    """{id du spot: phrases de l'« À savoir » valables à cette date}, pour les spots retravaillés."""
    if not spot_ids:
        return {}
    placeholders = ",".join(["%s"] * len(spot_ids))
    cursor.execute(f"""
        SELECT v.spot_id, v.a_savoir FROM spot_verifications v
        JOIN (SELECT spot_id, MAX(id) AS id FROM spot_verifications
              WHERE a_savoir IS NOT NULL AND spot_id IN ({placeholders}) GROUP BY spot_id) latest ON latest.id = v.id
    """, tuple(spot_ids))
    reworked = {row["spot_id"]: a_savoir_on(json.loads(row["a_savoir"]), on_date) for row in cursor.fetchall()}
    # Le texte corrigé par un relecteur prime sur celui de l'agent (vide : plus rien à signaler).
    cursor.execute(f"""
        SELECT d.objet_id, d.a_savoir_corrige FROM decisions d
        JOIN (SELECT objet_id, MAX(id) AS id FROM decisions
              WHERE objet_type = 'spot' AND annulee_at IS NULL AND objet_id IN ({placeholders})
              GROUP BY objet_id) latest ON latest.id = d.id
        WHERE d.a_savoir_corrige IS NOT NULL
    """, tuple(spot_ids))
    for row in cursor.fetchall():
        reworked[row["objet_id"]] = corrected_sentences(row["a_savoir_corrige"])
    return reworked


def _spot_labels(cursor, spot_ids: list) -> dict:
    if not spot_ids:
        return {}
    placeholders = ",".join(["%s"] * len(spot_ids))
    cursor.execute(f"""
        SELECT s.id, s.name, s.type, s.place_label, s.city_label, s.url, s.postal_code, s.address, s.latitude, s.longitude
        FROM spots s WHERE s.id IN ({placeholders})
    """, tuple(spot_ids))
    return {row["id"]: row for row in cursor.fetchall()}


def _name(spot: dict | None) -> str:
    if not spot:
        return "Spot inconnu"
    return spot_name_label(spot["place_label"], spot["city_label"], spot["name"], spot["type"])


def _a_savoir_text(stored: str | None) -> str:
    """L'« À savoir » de l'agent, une phrase par ligne, pour le champ de correction."""
    return "\n".join(item["texte"] for item in json.loads(stored or "[]"))


# LES FILTRES DE LA PAGE SPOTS (carte #186, 14 novembre 2026), comme ceux de Services et de Modifier :
# - ville : une ville de l'étape 1, par son identifiant. Un spot s'y range comme dans la recherche de Modifier
#   (services_edit.in_city) : par la commune de son adresse, sinon par la ville de l'appli la plus proche ;
# - commune : la commune de l'adresse d'un spot quand ce n'est pas une ville de l'appli ;
# - catégorie : gratuit, payant ou autres, le même classement que le filtre de l'étape 3 (display_utils.spot_category) ;
# - problème : les deux raisons pour lesquelles un spot attend l'administratrice (SPOT_PROBLEMS).
SPOT_CATEGORIES = ("gratuit", "payant", "autres")

# LES DEUX PROBLÈMES D'UN SPOT (14 novembre 2026) :
# - « retrait » : l'agent propose de le retirer ; le spot est masqué au voyageur en attendant la décision ;
# - « non_verifie » : le spot est proposé au voyageur avec le badge « non vérifié », le plus souvent parce que l'agent
#   doute (« incertain ») : 103 spots ce jour-là, que la page ne montrait pas. « Garder » le rend vérifié.
SPOT_PROBLEMS = {"retrait": "Retrait proposé", "non_verifie": "Non vérifié"}

# Les spots non vérifiés que l'étape 3 propose quand même : les mêmes conditions que proposable_spots
# (spot_selection_service), sans la zone d'une ville.
UNVERIFIED_SPOTS = """
    SELECT s.id FROM spots s
    WHERE s.verifie = 0 AND s.type IS NOT NULL AND s.type NOT IN ({marks})
      AND s.duplicate_of_spot_id IS NULL AND s.p4n_removed = 0
      AND (s.nuit_interdite IS NULL OR s.nuit_interdite = 0)
"""


def _unverified_ids(cursor, states: dict) -> list:
    """Les spots proposés au voyageur avec le badge « non vérifié » ; un spot retiré ou à relire n'en est pas."""
    cursor.execute(UNVERIFIED_SPOTS.format(marks=",".join(["%s"] * len(HIDDEN_SPOT_TYPES))), HIDDEN_SPOT_TYPES)
    return [row["id"] for row in cursor.fetchall()
            if spot_status(*states.get(row["id"], (None, None))) not in ("retire", "propose")]


def spot_town(spot: dict) -> str | None:
    """La commune d'un spot : celle de son adresse, sinon celle que park4night lui donne."""
    return address_town(spot.get("address")) or spot.get("city_label")


def spot_city(spot: dict, cities: list) -> dict | None:
    """La ville de l'appli où se range le spot, None s'il est dans une commune qui n'en est pas une."""
    # Import ici : services_edit charge la relecture des services et les agents, inutiles au reste de ce module.
    from services.supervision.services_edit import in_city
    town = spot_town(spot)
    return next((city for city in cities
                 if in_city(town, spot.get("latitude"), spot.get("longitude"), city, cities)), None)


def _place_fields(spot: dict, cities: list) -> dict:
    """Ce que les filtres lisent sur une carte : sa catégorie, sa ville de l'appli, ou sinon sa commune."""
    city = spot_city(spot, cities) if spot else None
    return {"categorie": spot_category(spot.get("type")), "ville_id": city["id"] if city else None,
            "commune": None if city else spot_town(spot), "code_postal": spot.get("postal_code")}


def filter_reviews(reviews: list, city_id: int | None, town: str | None, category: str | None,
                   problem: str | None = None) -> list:
    """Les cartes qui passent les filtres choisis ; un filtre vide (None) laisse tout passer."""
    return [review for review in reviews
            if (city_id is None or review["ville_id"] == city_id)
            and (not town or town_key(review["commune"]) == town_key(town))
            and (not category or review["categorie"] == category)
            and (not problem or review["probleme"] == problem)]


def city_choices(reviews: list, cities: list) -> tuple:
    """
    Ce que la recherche de ville propose (supervision_ville.js) : les villes qui ont des spots à relire, puis les
    communes qui n'en sont pas, chacune avec les codes postaux de ses spots.
    """
    city_codes, towns = {}, {}
    for review in reviews:
        codes = {review["code_postal"]} if review["code_postal"] else set()
        if review["ville_id"] is not None:
            city_codes.setdefault(review["ville_id"], set()).update(codes)
        elif review["commune"]:
            towns.setdefault(town_key(review["commune"]), {"nom": review["commune"], "codes": set()})["codes"].update(codes)
    offered = [{"id": city["id"], "name": city["name"], "codes": sorted(city_codes[city["id"]])}
               for city in cities if city["id"] in city_codes]
    return offered, [{"nom": town["nom"], "codes": sorted(town["codes"])} for _, town in sorted(towns.items())]


def _review_card(cursor, spot_id: int, verification: dict | None, spot: dict, cities: list, problem: str) -> dict:
    """
    La carte d'un spot à trancher : ce que l'agent a trouvé (sa dernière vérification, s'il y en a une), les derniers
    commentaires des voyageurs, et ce que lisent les filtres.
    """
    verification = verification or {}
    cursor.execute("SELECT review_date, text FROM spot_reviews WHERE spot_id = %s"
                   " ORDER BY review_date DESC LIMIT %s", (spot_id, PROOF_REVIEWS))
    reopening = verification.get("utilisable_a_partir")
    return {
        "objet_type": SPOT,
        "objet_id": spot_id,
        "probleme": problem,
        "verification_id": verification.get("id"),
        "nom": _name(spot),
        "url": spot.get("url"),
        "raison": verification.get("raison") or "",
        "resume": verification.get("resume") or "",
        "a_savoir": _a_savoir_text(verification.get("a_savoir")),
        "reouverture": reopening.strftime("%d/%m/%Y") if reopening else None,
        "sources": json.loads(verification.get("sources") or "[]"),
        "commentaires": [{"date": row["review_date"].strftime("%d/%m/%Y") if row["review_date"] else "",
                          "texte": row["text"] or ""} for row in cursor.fetchall()],
        **_place_fields(spot, cities),
    }


def get_reviews(city_id: int | None = None, town: str | None = None, category: str | None = None,
                problem: str | None = None) -> dict:
    """
    Les spots à trancher, avec les filtres de la page (une catégorie ou un problème inconnu est refusé), et les
    dernières décisions.
    """
    if category and category not in SPOT_CATEGORIES:
        raise ValueError(f"Catégorie inconnue : {category}")
    if problem and problem not in SPOT_PROBLEMS:
        raise ValueError(f"Problème inconnu : {problem}")
    connection = MySQLUtils.connect()
    try:
        cursor = connection.cursor(dictionary=True)
        states = _spot_states(cursor)
        removals = [spot_id for spot_id, (verification, decision) in states.items()
                    if spot_status(verification, decision) == "propose"]
        unverified = _unverified_ids(cursor, states)
        spots = _spot_labels(cursor, removals + unverified)
        cursor.execute(f"SELECT id, name, commune, latitude, longitude FROM cities WHERE {communes_only()} ORDER BY name")
        cities = cursor.fetchall()
        reviews = [_review_card(cursor, spot_id, states.get(spot_id, (None, None))[0], spots.get(spot_id) or {},
                                cities, file)
                   for file, spot_ids in (("retrait", removals), ("non_verifie", unverified)) for spot_id in spot_ids]
        reviews.sort(key=lambda review: review["objet_id"])
        # Les choix des filtres viennent de toute la file ; les nombres d'un menu suivent la ville et l'autre menu.
        offered_cities, towns = city_choices(reviews, cities)
        in_place = filter_reviews(reviews, city_id, town, None)
        category_counts = Counter(review["categorie"] for review in filter_reviews(in_place, None, None, None, problem))
        problem_counts = Counter(review["probleme"] for review in filter_reviews(in_place, None, None, category))
        reviews = filter_reviews(in_place, None, None, category, problem)

        cursor.execute("""
            SELECT d.*, (SELECT v.a_savoir FROM spot_verifications v WHERE v.id = d.verification_id) AS a_savoir_agent
            FROM decisions d WHERE d.objet_type = %s AND d.annulee_at IS NULL ORDER BY d.id DESC LIMIT %s
        """, (SPOT, RECENT_DECISIONS))
        recent = cursor.fetchall()
        spots = _spot_labels(cursor, [d["objet_id"] for d in recent])
        openings = _opening_decisions(cursor)
        cursor.close()
        return {"reviews": reviews,
                "cities": offered_cities, "towns": towns,
                "categories": [{"code": code, "nombre": category_counts[code]} for code in SPOT_CATEGORIES],
                "problemes": [{"code": code, "label": label, "nombre": problem_counts[code]}
                              for code, label in SPOT_PROBLEMS.items()],
                "notation": rating.labels(),
                "ouvertures": openings,
                "recent": [{"id": d["id"], "nom": _name(spots.get(d["objet_id"])), "decision": d["decision"],
                            "note": d["note"] or "", "par": d["decided_by"],
                            "a_savoir": (d["a_savoir_corrige"] if d["a_savoir_corrige"] is not None
                                         else _a_savoir_text(d["a_savoir_agent"])),
                            "le": paris_date_text(d["decided_at"])} for d in recent]}
    finally:
        MySQLUtils.disconnect(connection)


def _day_month(month_day: str | None) -> str:
    return f"{month_day[3:]}/{month_day[:2]}" if month_day else "?"


def _opening_decisions(cursor) -> list:
    """Les ouvertures tranchées par un humain, et si le texte de la fiche a changé depuis."""
    cursor.execute("""
        SELECT d.id, d.objet_id, d.decision, d.note, d.decided_by, d.decided_at, d.detail, s.opening_period
        FROM decisions d JOIN spots s ON s.id = d.objet_id
        WHERE d.objet_type = %s AND d.annulee_at IS NULL ORDER BY d.objet_id
    """, (OPENING_OBJECT,))
    rows = cursor.fetchall()
    spots = _spot_labels(cursor, [row["objet_id"] for row in rows])
    openings = []
    for row in rows:
        detail = json.loads(row["detail"])
        spot = spots.get(row["objet_id"]) or {}
        openings.append({
            "id": row["id"],
            "objet_id": row["objet_id"],
            "nom": _name(spot),
            "url": spot.get("url"),
            "statut": row["decision"],
            "debut": _day_month(detail["debut"]),
            "fin": _day_month(detail["fin"]),
            "convention": detail["convention"],
            "texte": row["opening_period"] or "",
            "texte_decide": detail["texte"] or "",
            "texte_change": row["opening_period"] != detail["texte"],
            "note": row["note"] or "",
            "par": row["decided_by"],
            "le": paris_date_text(row["decided_at"]),
        })
    return openings


def decide_opening(spot_id: int, status: str, start: str | None, end: str | None, note: str, decided_by: str,
                   convention: bool = False) -> None:
    """
    Fixe la lecture de l'ouverture d'un spot, à la place de read_openings. `convention` : au moins
    une des dates n'est pas donnée par la fiche. Une décision déjà en vigueur est remplacée.
    """
    if status not in OPENING_STATUSES:
        raise ValueError(f"Statut d'ouverture inconnu : {status}")
    if (status == "periode") != bool(start and end):
        raise ValueError("Deux dates pour une période, aucune sinon")
    connection = MySQLUtils.connect()
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("""
            SELECT opening_period, ouverture_statut, ouverture_debut, ouverture_fin, ouverture_lue
            FROM spots WHERE id = %s
        """, (spot_id,))
        spot = cursor.fetchone()
        if not spot:
            raise ValueError(f"Spot inconnu : {spot_id}")
        cursor.execute("""
            SELECT detail FROM decisions WHERE objet_type = %s AND objet_id = %s AND annulee_at IS NULL
            ORDER BY id LIMIT 1
        """, (OPENING_OBJECT, spot_id))
        current = cursor.fetchone()
        # On remplace une décision : les valeurs à remettre restent celles d'avant la première.
        before = json.loads(current["detail"])["avant"] if current else {
            "statut": spot["ouverture_statut"], "debut": spot["ouverture_debut"],
            "fin": spot["ouverture_fin"], "lue": spot["ouverture_lue"]}
        cursor.execute("UPDATE decisions SET annulee_at = NOW() WHERE objet_type = %s AND objet_id = %s"
                       " AND annulee_at IS NULL", (OPENING_OBJECT, spot_id))
        detail = {"debut": start, "fin": end, "convention": convention, "texte": spot["opening_period"],
                  "avant": before}
        record_decision(cursor, OPENING_OBJECT, spot_id, status, note, decided_by, detail)
        cursor.execute("""
            UPDATE spots SET ouverture_statut = %s, ouverture_debut = %s, ouverture_fin = %s, ouverture_lue = %s
            WHERE id = %s
        """, (status, start, end, spot["opening_period"], spot_id))
        connection.commit()
        cursor.close()
    finally:
        MySQLUtils.disconnect(connection)


def undo_opening_decision(cursor, spot_id: int, detail: dict) -> None:
    """
    Défait une ouverture décidée (appelée par decisions.cancel_decision) : les valeurs d'avant reviennent, et
    read_openings relira le spot.
    """
    before = detail["avant"]
    cursor.execute("""
        UPDATE spots SET ouverture_statut = %s, ouverture_debut = %s, ouverture_fin = %s, ouverture_lue = NULL
        WHERE id = %s
    """, (before["statut"], before["debut"], before["fin"], spot_id))


def decide(spot_id: int, decision: str, note: str, decided_by: str, a_savoir: str | None = None,
           pertinence: str | None = None, raison: str | None = None) -> None:
    """
    Enregistre la décision sur un spot, en réponse à sa dernière vérification. Le badge suit :
    un spot gardé par un humain est vérifié, un spot retiré ne l'est pas. `a_savoir` : le texte
    corrigé par le relecteur, None pour garder celui de l'agent. pertinence et raison : la note facultative
    donnée à la proposition de l'agent (rating), déjà vérifiée par la route ; None si elle n'est pas notée.
    """
    if decision not in DECISIONS:
        raise ValueError(f"Décision inconnue : {decision}")
    connection = MySQLUtils.connect()
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT MAX(id) AS id FROM spot_verifications WHERE spot_id = %s", (spot_id,))
        verification_id = cursor.fetchone()["id"]
        # Le badge d'avant, remis si on annule : la plupart des spots sont vérifiés sans aucune décision.
        cursor.execute("SELECT verifie FROM spots WHERE id = %s", (spot_id,))
        spot = cursor.fetchone()
        if not spot:
            raise ValueError(f"Spot inconnu : {spot_id}")
        detail = {"avant": {"verifie": bool(spot["verifie"])}}
        record_decision(cursor, SPOT, spot_id, decision, note, decided_by, detail,
                        verification_id=verification_id, a_savoir_corrige=a_savoir,
                        pertinence=pertinence, raison=raison)
        cursor.execute("UPDATE spots SET verifie = %s WHERE id = %s", (decision == "garder", spot_id))
        connection.commit()
        cursor.close()
    finally:
        MySQLUtils.disconnect(connection)


def correct_a_savoir(decision_id: int, a_savoir: str) -> None:
    """
    Corrige le texte d'une décision déjà prise sur un spot, sans la refaire. Refuse (ValueError) un numéro qui n'est
    pas celui d'une décision de spot encore valable : un service ou une décision annulée n'a pas de texte « À savoir ».
    """
    connection = MySQLUtils.connect()
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT id FROM decisions WHERE id = %s AND objet_type = %s AND annulee_at IS NULL",
                       (decision_id, SPOT))
        if not cursor.fetchone():
            raise ValueError("Décision de spot introuvable ou annulée")
        cursor.execute("UPDATE decisions SET a_savoir_corrige = %s WHERE id = %s", (a_savoir, decision_id))
        connection.commit()
        cursor.close()
    finally:
        MySQLUtils.disconnect(connection)


def undo_spot_decision(cursor, spot_id: int, detail: dict) -> None:
    """
    Défait une décision sur un spot (appelée par decisions.cancel_decision) : le spot revient à la relecture et son
    badge reprend sa valeur d'avant. Une décision plus ancienne n'a pas gardé cette valeur : le doute revient, le
    badge part.
    """
    before = detail.get("avant", {})
    cursor.execute("UPDATE spots SET verifie = %s WHERE id = %s", (bool(before.get("verifie", False)), spot_id))
