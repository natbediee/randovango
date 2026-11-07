"""
Supervision, onglet « Modifier » : corriger n'importe quel service, même sans signal à relire (7 novembre 2026).

La relecture (poi_review_service.py) ne montre que les lieux qu'une vérification a signalés. Une erreur vue sur
une carte de l'étape 4 (la Cave de Keruzas, sans aucun signal) ne pouvait pas y être corrigée. Ici, on retrouve
le lieu comme le voyageur le voit, puis on le corrige.

LES MÊMES LIEUX QUE L'ÉTAPE 4 : la ville choisie donne la même zone que step4.py (ZONE_KM autour du centre, plus
les restaurants et commerces dont l'adresse finit par la commune). Les lieux masqués sont montrés aussi, pour
pouvoir les remettre.

LES MÊMES CORRECTIONS QUE LA RELECTURE, et le même code : applied_fields, typed_name, typed_link, typed_maps_link.
Chaque correction est une décision (objet_type = 'poi', detail.file = 'modifier') qui garde les valeurs d'avant :
poi_review_service.cancel_decision la défait. Les noms de décision sont ceux de la relecture : un agent ne touche
pas un nom ou un lien corrigé ici (restaurant_service._decided_by_human).
"""
import json

from services import poi_review_service as review
from utils.db_utils import MySQLUtils
from utils.geo_utils import get_bounding_box

EDIT_FILE = "modifier"
ZONE_KM = 5          # le rayon par défaut de l'étape 4 (step4.py)
PAGE_SIZE = 50
RECENT_DECISIONS = 10
MIN_NAME_SEARCH = 2
EDIT_ACTIONS = ("autre_nom", "autre_lien", "retirer_lien", "autre_maps", "retirer", "garder",
                "valider_saison", "pas_saisonnier")
EDIT_BUTTONS = {"retirer": "Retirer le lieu", "garder": "Remettre le lieu", "retirer_lien": "Retirer le lien",
                "valider_saison": "Saisonnier : ces mois", "pas_saisonnier": "Pas saisonnier"}


def place_actions(poi: dict) -> list:
    """Les corrections possibles sur un lieu, selon ce qu'il est aujourd'hui."""
    actions = ["autre_nom", "autre_lien"] + (["retirer_lien"] if poi.get("url") else []) + ["autre_maps"]
    actions.append("garder" if poi.get("masque") else "retirer")
    actions.append("valider_saison")
    if poi.get("statut_saison"):
        actions.append("pas_saisonnier")
    return actions


def _months(value) -> list:
    if not value:
        return []
    months = json.loads(value) if isinstance(value, str) else value
    return [month for month in months if isinstance(month, int)]


def place_card(row: dict) -> dict:
    """La fiche d'un lieu à corriger : ce que voit le voyageur, et les corrections possibles."""
    precise = review.SHEET_LABELS.get(row.get("table_categorie") or row.get("shop_categorie")) or row.get("service_name")
    return {
        "poi_id": row["id"], "nom": row["name"], "adresse": row.get("address") or "", "commune": row.get("commune") or "",
        "service": precise or "", "onglet": review.step4_tab(row.get("service_category")),
        "url_actuelle": row.get("url"), "maps_actuel": row.get("maps_url"),
        "position": [float(row["latitude"]), float(row["longitude"])] if row.get("latitude") is not None else None,
        "masque": bool(row.get("masque")), "ferme_moment": bool(row.get("ferme_moment")),
        "statut_saison": row.get("statut_saison"), "months": _months(row.get("mois_ouverture")),
        "actions": place_actions(row),
    }


def _city(cursor, city_id: int | None) -> dict | None:
    if city_id is None:
        return None
    cursor.execute("SELECT id, name, latitude, longitude FROM cities WHERE id = %s", (city_id,))
    city = cursor.fetchone()
    if not city:
        raise ValueError(f"Ville inconnue : {city_id}")
    return city


def _search_rows(cursor, city: dict | None, name: str) -> list:
    filters, params = [], []
    if city:
        min_lat, min_lon, max_lat, max_lon = get_bounding_box(city["latitude"], city["longitude"], ZONE_KM)
        # La même zone que step4.py : une commune déborde (la Pointe Saint-Mathieu, à 5,2 km de Plougonvelin).
        filters.append("((p.latitude BETWEEN %s AND %s AND p.longitude BETWEEN %s AND %s)"
                       " OR ((EXISTS (SELECT 1 FROM restaurants r WHERE r.poi_id = p.id)"
                       " OR EXISTS (SELECT 1 FROM commerces c WHERE c.poi_id = p.id)) AND p.address LIKE %s))")
        params += [min_lat, max_lat, min_lon, max_lon, f"%{city['name']}"]
    if name:
        filters.append("p.name LIKE %s")
        params.append(f"%{name}%")
    cursor.execute(f"""
        SELECT p.id, p.name, p.address, p.url, p.maps_url, p.latitude, p.longitude, p.masque, p.ferme_moment,
               p.statut_saison, p.mois_ouverture,
               (SELECT MIN(s.name) FROM poi_service ps JOIN services s ON s.id = ps.service_id
                WHERE ps.poi_id = p.id) AS service_name,
               (SELECT MIN(s.category) FROM poi_service ps JOIN services s ON s.id = ps.service_id
                WHERE ps.poi_id = p.id) AS service_category,
               (SELECT r.categorie FROM restaurants r WHERE r.poi_id = p.id) AS table_categorie,
               (SELECT c.categorie FROM commerces c WHERE c.poi_id = p.id) AS shop_categorie,
               (SELECT MIN(c.name) FROM histo_poi h JOIN cities c ON c.id = h.city_id WHERE h.poi_id = p.id) AS commune
        FROM poi p WHERE {' AND '.join(filters)}
    """, tuple(params))
    return cursor.fetchall()


def filter_cards(rows: list, service: str | None, kind: str | None) -> tuple:
    """Les fiches dans l'onglet et le type choisis, et les compteurs des filtres (comme la relecture)."""
    cards = [place_card(row) for row in rows]
    service_counts, type_counts = {}, {}
    for card in cards:
        service_counts[card["onglet"]] = service_counts.get(card["onglet"], 0) + 1
        if service and card["onglet"] == service:
            type_counts[card["service"]] = type_counts.get(card["service"], 0) + 1
    chosen = [card for card in cards
              if (not service or card["onglet"] == service) and (not kind or card["service"] == kind)]
    chosen.sort(key=lambda card: (card["nom"] or "").lower())
    return chosen, service_counts, type_counts


def _recent(cursor) -> list:
    cursor.execute("""
        SELECT d.id, d.decision, d.note, d.decided_by, d.decided_at, p.name FROM decisions d
        JOIN poi p ON p.id = d.objet_id
        WHERE d.objet_type = %s AND d.annulee_at IS NULL AND JSON_UNQUOTE(JSON_EXTRACT(d.detail, '$.file')) = %s
        ORDER BY d.id DESC LIMIT %s
    """, (review.POI, EDIT_FILE, RECENT_DECISIONS))
    return [{"id": row["id"], "nom": row["name"], "action": review.ACTION_LABELS.get(row["decision"], row["decision"]),
             "note": row["note"] or "", "par": row["decided_by"], "le": row["decided_at"].strftime("%d/%m/%Y")}
            for row in cursor.fetchall()]


def search(city_id: int | None = None, service: str | None = None, kind: str | None = None, name: str | None = None) -> dict:
    """
    Les lieux d'une ville, d'un onglet de l'étape 4, d'un type précis, et dont le nom contient `name`. Il faut une ville
    ou un bout de nom : sans eux, toute la table viendrait.
    """
    name = " ".join((name or "").split())
    connection = MySQLUtils.connect()
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT id, name FROM cities ORDER BY name")
        cities = cursor.fetchall()
        city = _city(cursor, city_id)
        cards, service_counts, type_counts = [], {}, {}
        if city or len(name) >= MIN_NAME_SEARCH:
            cards, service_counts, type_counts = filter_cards(_search_rows(cursor, city, name), service, kind)
        recent = _recent(cursor)
        cursor.close()
        return {"cities": cities, "cards": cards[:PAGE_SIZE], "total": len(cards), "service_counts": service_counts,
                "type_counts": type_counts, "recent": recent, "buttons": EDIT_BUTTONS,
                "searched": bool(city or len(name) >= MIN_NAME_SEARCH)}
    finally:
        MySQLUtils.disconnect(connection)


def decide_one(cursor, poi_id: int, action: str, note: str, decided_by: str, months: list | None = None,
               url: str | None = None, name: str | None = None) -> None:
    """Applique une correction et la trace, avec les valeurs d'avant pour pouvoir l'annuler."""
    if action not in EDIT_ACTIONS:
        raise ValueError(f"Correction inconnue : {action}")
    cursor.execute(f"SELECT {', '.join(review.APPLIED_COLUMNS)} FROM poi WHERE id = %s", (poi_id,))
    before = cursor.fetchone()
    if not before:
        raise ValueError(f"Lieu inconnu : {poi_id}")
    if action not in place_actions(before):
        raise ValueError(f"Correction impossible sur ce lieu : {action}")
    # Hors de la file des fermetures, renommer ne remet pas un lieu masqué : on le remet à part (« Remettre le lieu »).
    fields = review.applied_fields(action, {"tab": EDIT_FILE}, months, url, name)
    if fields:
        assignments = ", ".join(f"{column} = %s" for column in fields)
        cursor.execute(f"UPDATE poi SET {assignments} WHERE id = %s", (*fields.values(), poi_id))
    signal_ids = []
    if action == "retirer":
        # Comme dans la relecture : un lieu retiré sort de toutes les files, et y revient si on annule.
        cursor.execute("SELECT id FROM poi_signals WHERE poi_id = %s AND statut = 'a_relire'", (poi_id,))
        signal_ids = [row["id"] for row in cursor.fetchall()]
        if signal_ids:
            marks = ",".join(["%s"] * len(signal_ids))
            cursor.execute(f"UPDATE poi_signals SET statut = %s, reviewed_at = NOW() WHERE id IN ({marks})",
                           (review.ACTIONS[action], *signal_ids))
    detail = {"file": EDIT_FILE, "signal_ids": signal_ids, "avant": {column: before[column] for column in fields}}
    cursor.execute("""
        INSERT INTO decisions (objet_type, objet_id, decision, note, decided_by, decided_at, detail)
        VALUES (%s, %s, %s, %s, %s, NOW(), %s)
    """, (review.POI, poi_id, action, (note or "").strip()[:255] or None, decided_by,
          json.dumps(detail, ensure_ascii=False, default=str)))


def decide(poi_id: int, action: str, note: str, decided_by: str, months: list | None = None,
           url: str | None = None, name: str | None = None) -> None:
    connection = MySQLUtils.connect()
    try:
        cursor = connection.cursor(dictionary=True)
        decide_one(cursor, poi_id, action, note, decided_by, months, url, name)
        connection.commit()
        cursor.close()
    except Exception:
        connection.rollback()
        raise
    finally:
        MySQLUtils.disconnect(connection)
