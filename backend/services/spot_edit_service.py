"""
Supervision, onglet « Modifier » : corriger n'importe quel spot, même sans vérification à relire (7 novembre 2026).

La relecture des spots (supervision_service.py) ne montre que ceux que verify_spots.py propose de retirer. Ici, on
retrouve un spot comme le voyageur le voit à l'étape 3 (la même zone autour de la ville, ZONE_KM), puis on le corrige
avec les décisions qui existent déjà, sans en inventer :
    retirer ou garder (supervision_service.decide), avec l'« À savoir » corrigé ;
    les dates d'ouverture (supervision_service.decide_opening).
Chacune s'annule avec le code de la relecture (cancel_decision, cancel_opening_decision).
"""
import re
from datetime import date

from services import supervision_service as supervision
from services.poi_edit_service import address_town, in_city
from utils.db_utils import MySQLUtils
from utils.geo_utils import city_commune, get_bounding_box

ZONE_KM = 5          # le rayon par défaut de l'étape 3 (step3.py)
PAGE_SIZE = 50
RECENT_DECISIONS = 10
MIN_NAME_SEARCH = 2
STATUS_LABELS = {"retire": "Retiré", "garde": "Gardé par un humain", "propose": "Retrait à relire", "normal": "Affiché"}
DECISION_LABELS = {"retirer": "retiré", "garder": "gardé", "toute_annee": "ouvert toute l'année",
                   "periode": "ouvert sur une période", "saison": "saisonnier", "inconnue": "ouverture inconnue"}


def typed_day(value: str | None) -> str | None:
    """Une date d'ouverture tapée « JJ/MM », rangée comme en base : « MM-JJ ». Vide : pas de date."""
    value = (value or "").strip()
    if not value:
        return None
    match = re.fullmatch(r"(\d{1,2})/(\d{1,2})", value)
    if not match:
        raise ValueError("Date invalide : écris-la JJ/MM, par exemple 15/04")
    day, month = int(match.group(1)), int(match.group(2))
    try:
        date(2024, month, day)   # une année bissextile : le 29/02 est une vraie date
    except ValueError:
        raise ValueError(f"Date invalide : {value}")
    return f"{month:02d}-{day:02d}"


def _day_month(month_day: str | None) -> str:
    return f"{month_day[3:]}/{month_day[:2]}" if month_day else ""


def spot_card(spot: dict, verification: dict | None, decision: dict | None, a_savoir: list,
              opening_decision_id: int | None) -> dict:
    status = supervision.spot_status(verification, decision)
    return {
        "spot_id": spot["id"], "nom": supervision._name(spot), "type": spot.get("type") or "",
        "url": spot.get("url"), "position": [float(spot["latitude"]), float(spot["longitude"])],
        "statut": status, "statut_label": STATUS_LABELS[status], "verifie": bool(spot.get("verifie")),
        "nuit_interdite": bool(spot.get("nuit_interdite")),
        "a_savoir": "\n".join(a_savoir),
        # La décision en vigueur, pour l'annuler ou corriger son texte.
        "decision_id": decision["id"] if decision else None,
        "decision": decision["decision"] if decision else None,
        "ouverture": {"statut": spot.get("ouverture_statut") or "", "debut": _day_month(spot.get("ouverture_debut")),
                      "fin": _day_month(spot.get("ouverture_fin")), "texte": spot.get("opening_period") or "",
                      "decision_id": opening_decision_id},
    }


def _search_rows(cursor, city: dict | None, name: str, cities: list | None = None) -> list:
    # Les spots que l'étape 3 peut proposer (spot_selection_service.proposable_spots), masqués compris.
    filters, params = ["s.duplicate_of_spot_id IS NULL", "s.p4n_removed = 0"], []
    if city:
        min_lat, min_lon, max_lat, max_lon = get_bounding_box(city["latitude"], city["longitude"], ZONE_KM)
        # Comme pour les services (poi_edit_service.in_city) : la commune du spot, sinon la ville la plus proche.
        filters.append("((s.latitude BETWEEN %s AND %s AND s.longitude BETWEEN %s AND %s) OR s.address LIKE %s OR s.city_label IN (%s, %s))")
        params += [min_lat, max_lat, min_lon, max_lon, f"%{city_commune(city)}", city["name"], city_commune(city)]
    if name:
        filters.append("(s.name LIKE %s OR s.place_label LIKE %s)")
        params += [f"%{name}%", f"%{name}%"]
    cursor.execute(f"""
        SELECT s.id, s.name, s.type, s.place_label, s.city_label, s.address, s.url, s.postal_code, s.latitude, s.longitude,
               s.verifie, s.nuit_interdite, s.opening_period, s.ouverture_statut, s.ouverture_debut, s.ouverture_fin
        FROM spots s WHERE {' AND '.join(filters)}
    """, tuple(params))
    rows = cursor.fetchall()
    if not city:
        return rows
    return [row for row in rows
            if in_city(address_town(row.get("address")) or row.get("city_label"), row["latitude"], row["longitude"], city, cities)]


def _opening_ids(cursor, spot_ids: list) -> dict:
    if not spot_ids:
        return {}
    marks = ",".join(["%s"] * len(spot_ids))
    cursor.execute(f"""
        SELECT objet_id, MAX(id) AS id FROM decisions
        WHERE objet_type = %s AND annulee_at IS NULL AND objet_id IN ({marks}) GROUP BY objet_id
    """, (supervision.OPENING_OBJECT, *spot_ids))
    return {row["objet_id"]: row["id"] for row in cursor.fetchall()}


def _recent(cursor) -> list:
    cursor.execute("""
        SELECT d.id, d.objet_type, d.objet_id, d.decision, d.note, d.decided_by, d.decided_at FROM decisions d
        WHERE d.objet_type IN (%s, %s) AND d.annulee_at IS NULL ORDER BY d.id DESC LIMIT %s
    """, (supervision.SPOT, supervision.OPENING_OBJECT, RECENT_DECISIONS))
    rows = cursor.fetchall()
    spots = supervision._spot_labels(cursor, [row["objet_id"] for row in rows])
    return [{"id": row["id"], "ouverture": row["objet_type"] == supervision.OPENING_OBJECT,
             "nom": supervision._name(spots.get(row["objet_id"])),
             "action": DECISION_LABELS.get(row["decision"], row["decision"]), "note": row["note"] or "",
             "par": row["decided_by"], "le": row["decided_at"].strftime("%d/%m/%Y")} for row in rows]


def search(city_id: int | None = None, name: str | None = None, on_date: date | None = None) -> dict:
    """Les spots d'une ville dont le nom contient `name`. Il faut une ville ou un bout de nom."""
    name = " ".join((name or "").split())
    connection = MySQLUtils.connect()
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT id, name, latitude, longitude FROM cities ORDER BY name")
        all_cities = cursor.fetchall()
        cities = [{"id": row["id"], "name": row["name"]} for row in all_cities]
        city = None
        if city_id is not None:
            cursor.execute("SELECT id, name, commune, latitude, longitude FROM cities WHERE id = %s", (city_id,))
            city = cursor.fetchone()
            if not city:
                raise ValueError(f"Ville inconnue : {city_id}")
        searched = bool(city or len(name) >= MIN_NAME_SEARCH)
        cards = []
        if searched:
            rows = _search_rows(cursor, city, name, all_cities)
            ids = [row["id"] for row in rows]
            states = supervision._spot_states(cursor)
            texts = supervision.reworked_a_savoir(cursor, ids, on_date or date.today())
            openings = _opening_ids(cursor, ids)
            cards = [spot_card(row, *states.get(row["id"], (None, None)), texts.get(row["id"], []), openings.get(row["id"]))
                     for row in rows]
            cards.sort(key=lambda card: card["nom"].lower())
        recent = _recent(cursor)
        cursor.close()
        return {"cities": cities, "cards": cards[:PAGE_SIZE], "total": len(cards), "recent": recent,
                "searched": searched}
    finally:
        MySQLUtils.disconnect(connection)


def decide_opening(spot_id: int, status: str, start: str | None, end: str | None, note: str, decided_by: str,
                   convention: bool = False) -> None:
    """
    Les dates tapées « JJ/MM ». `convention` : l'admin les a choisies, la fiche ne les donne pas
    (supervision_service.decide_opening). Hors d'une période, aucune date.
    """
    first, last = typed_day(start), typed_day(end)
    if status != "periode":
        first = last = None
        convention = False
    supervision.decide_opening(spot_id, status, first, last, note, decided_by, convention=convention)
