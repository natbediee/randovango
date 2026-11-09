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
import re
import unicodedata

from services import commerce_service, poi_review_service as review, restaurant_service
from services.commerce_selection_service import SHOP_CATEGORY_LABELS
from services.restaurant_selection_service import CONFIRMED_SEASON, PROBABLE_SEASON, TABLE_CATEGORY_LABELS, season_label
from utils.db_utils import MySQLUtils
from utils.geo_utils import city_commune, get_bounding_box, haversine_distance_km

EDIT_FILE = "modifier"
ZONE_KM = 5          # le rayon par défaut de l'étape 4 (step4.py)
PAGE_SIZE = 50
RECENT_DECISIONS = 10
MIN_NAME_SEARCH = 2
EDIT_ACTIONS = ("autre_nom", "autre_lien", "retirer_lien", "autre_maps", "retirer", "garder",
                "valider_saison", "pas_saisonnier")
FIELD_NAMES = {"name": "nom", "address": "adresse", "url": "lien", "maps_url": "lien Google Maps", "description": "texte",
               "pourquoi": "texte", "genre": "genre", "categorie": "type", "distinction": "distinction", "jours": "jours",
               "saison": "saison", "masque": "affichage"}
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
    cursor.execute("SELECT id, name, commune, latitude, longitude FROM cities WHERE id = %s", (city_id,))
    city = cursor.fetchone()
    if not city:
        raise ValueError(f"Ville inconnue : {city_id}")
    return city


# LA VILLE DU FILTRE, C'EST CELLE DE L'ADRESSE (8 novembre 2026). La zone de l'étape 4, un carré de ZONE_KM autour du
# centre, passe la mer : filtrer sur Île-de-Batz montrait 215 lieux, dont 122 de Roscoff et de Santec, et 8 « Abri »
# dont un seul sur l'île. Un lieu avec une adresse appartient à la commune de son adresse ; sans adresse, à la ville
# de l'appli la plus proche. Seule la supervision suit cette règle : l'étape 4 garde sa zone.
ADDRESS_TOWN = re.compile(r"\b\d{5}\s+([^,]+?)\s*$")


def address_town(address: str | None) -> str | None:
    """La commune d'une adresse « Quai Neuf, 29680 Roscoff » : ce qui suit le code postal."""
    match = ADDRESS_TOWN.search(address or "")
    return match.group(1) if match else None


def town_key(town: str | None) -> str:
    """« Île-de-Batz », « ile de batz » et « ILE-DE-BATZ » sont la même commune."""
    plain = unicodedata.normalize("NFKD", town or "").encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[-'’]", " ", plain).lower().split())


def in_city(town: str | None, latitude, longitude, city: dict, cities: list) -> bool:
    """
    Le lieu est-il dans la ville du filtre ? Sa commune s'il en a une, sinon la ville de l'appli la plus proche.
    Une adresse écrit la commune officielle (« 29810 Plouarzel »), pas le lieu-dit de la ville (Trézien) : les deux
    sont acceptés, le nom restant celui d'un spot étiqueté par Park4Night.
    """
    if town:
        return town_key(town) in {town_key(city["name"]), town_key(city_commune(city))}
    if latitude is None or longitude is None:
        return False
    nearest = min(cities, key=lambda other: haversine_distance_km(float(latitude), float(longitude),
                                                                  other["latitude"], other["longitude"]))
    return nearest["id"] == city["id"]


def _search_rows(cursor, city: dict | None, name: str, cities: list | None = None) -> list:
    filters, params = [], []
    if city:
        min_lat, min_lon, max_lat, max_lon = get_bounding_box(city["latitude"], city["longitude"], ZONE_KM)
        # Les candidats : la zone de l'étape 4, plus les adresses de la commune hors de la zone (la Pointe Saint-Mathieu,
        # à 5,2 km de Plougonvelin). in_city tranche ensuite.
        filters.append("((p.latitude BETWEEN %s AND %s AND p.longitude BETWEEN %s AND %s) OR p.address LIKE %s)")
        params += [min_lat, max_lat, min_lon, max_lon, f"%{city_commune(city)}"]
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
    rows = cursor.fetchall()
    for row in rows:
        # La commune affichée : celle de l'adresse, pas la première des villes dont la zone contient le lieu.
        row["commune"] = address_town(row.get("address")) or (city_commune(city) if city else row.get("commune"))
    if not city:
        return rows
    return [row for row in rows if in_city(address_town(row.get("address")), row["latitude"], row["longitude"], city, cities)]


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
        SELECT d.id, d.decision, d.note, d.decided_by, d.decided_at, d.detail, p.name FROM decisions d
        JOIN poi p ON p.id = d.objet_id
        WHERE d.objet_type = %s AND d.annulee_at IS NULL AND JSON_UNQUOTE(JSON_EXTRACT(d.detail, '$.file')) = %s
        ORDER BY d.id DESC LIMIT %s
    """, (review.POI, EDIT_FILE, RECENT_DECISIONS))
    return [{"id": row["id"], "nom": row["name"], "action": review.ACTION_LABELS.get(row["decision"], row["decision"]),
             "champs": ", ".join(FIELD_NAMES.get(field, field) for field in review.signal_detail(row).get("champs", [])),
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
        cursor.execute("SELECT id, name, latitude, longitude FROM cities ORDER BY name")
        all_cities = cursor.fetchall()
        cities = [{"id": row["id"], "name": row["name"]} for row in all_cities]
        city = _city(cursor, city_id)
        cards, service_counts, type_counts = [], {}, {}
        if city or len(name) >= MIN_NAME_SEARCH:
            cards, service_counts, type_counts = filter_cards(_search_rows(cursor, city, name, all_cities), service, kind)
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


# --- La fiche complète (8 novembre 2026) -------------------------------------------------------------------------------
# Tout ce que le voyageur voit d'un service à l'étape 4, modifiable en une fois : le nom, l'adresse, les liens, le texte,
# la saison, et la fiche de l'agent (genre, type affiché, distinction d'un restaurant, jours d'un marché). Un seul
# enregistrement = une décision « modifier_fiche », qui garde tout ce qu'elle change pour l'annuler.
#
# LE TEXTE PRÉSENTÉ : l'étape 4 montre poi.description (OSM) s'il existe, sinon le « pourquoi » de la fiche. On corrige
# celui qu'elle montre.
#
# LA FICHE D'UN LIEU À CONFIRMER n'est pas encore en table : elle attend dans son signal (poi_signals.detail["fiche"]).
# On la corrige là, et « Confirmer et afficher le lieu » écrit la fiche corrigée.

SHEET_DECISION = "modifier_fiche"
SOURCE_TABLES = {restaurant_service.SOURCE: "restaurants", commerce_service.SOURCE: "commerces"}
TABLE_LABELS = {"restaurants": TABLE_CATEGORY_LABELS, "commerces": SHOP_CATEGORY_LABELS}
TEXT_LIMITS = {"address": 255, "texte": 1000, "genre": 100, "distinction": 100, "jours": 150}
SEASONS = (None, PROBABLE_SEASON, CONFIRMED_SEASON)
# Ce que le signal d'une file met en doute : la page encadre ces champs.
DOUBT_FIELDS = {"liens": ["url"], "fermetures": ["name"], "saison": ["saison"], "morts": ["url"],
                "doublons": ["name", "address"], "confirmer": ["texte", "address", "genre"]}
# Corriger dans une file le champ qu'elle met en doute la tranche, comme « Renommer ainsi » et « Mettre ce lien ».
CLOSING_FIELDS = {"fermetures": ("name", "valide"), "liens": ("url", "rejete"), "saison": ("saison", "valide")}
# Les champs qu'une ancienne décision de la relecture a tranchés (human_fields).
LEGACY_FIELDS = {**{action: "name" for action in restaurant_service.HUMAN_NAME_DECISIONS},
                 **{action: "url" for action in restaurant_service.HUMAN_LINK_DECISIONS if action != "valider_lien_nom"},
                 "valider_lien_nom": "name", "valider_saison": "saison", "pas_saisonnier": "saison", "autre_maps": "maps_url"}
POI_SHEET_COLUMNS = ("name", "address", "url", "maps_url", "description", "statut_saison", "mois_ouverture", "verifie")


def load_sheet(cursor, poi_id: int) -> dict | None:
    """La fiche de l'agent : dans sa table, sinon celle qui attend dans le signal d'un lieu à confirmer, sinon None."""
    for table, columns in review.SHEET_COLUMNS.items():
        cursor.execute(f"SELECT {', '.join(columns)} FROM {table} WHERE poi_id = %s", (poi_id,))
        row = cursor.fetchone()
        if row:
            return {"origine": "table", "table": table, "values": dict(row)}
    cursor.execute("""
        SELECT id, source, detail FROM poi_signals WHERE poi_id = %s AND signal_type = 'a_confirmer'
        AND statut = 'a_relire' ORDER BY id DESC LIMIT 1
    """, (poi_id,))
    signal = cursor.fetchone()
    table = SOURCE_TABLES.get(signal["source"]) if signal else None
    fiche = review.signal_detail(signal).get("fiche") if table else None
    if not fiche:
        return None
    return {"origine": "signal", "table": table, "signal_id": signal["id"],
            "values": {column: fiche.get(column) for column in review.SHEET_COLUMNS[table]}}


def sheet_view(poi: dict, sheet: dict | None, service_name: str | None = None) -> dict:
    """La fiche telle que la page la montre : les valeurs du formulaire, et l'aperçu de l'étape 4."""
    values = (sheet or {}).get("values") or {}
    table = (sheet or {}).get("table")
    labels = TABLE_LABELS.get(table, {})
    text_target = "description" if poi.get("description") or not sheet else "pourquoi"
    months = _months(poi.get("mois_ouverture"))
    fields = ["name", "address", "url", "maps_url", "texte", "saison"]
    if sheet:
        fields += ["genre", "categorie", "distinction" if table == "restaurants" else "jours"]
    return {
        "poi_id": poi["id"], "nom": poi.get("name") or "", "adresse": poi.get("address") or "",
        "url": poi.get("url") or "", "maps_url": poi.get("maps_url") or "",
        "position": [float(poi["latitude"]), float(poi["longitude"])] if poi.get("latitude") is not None else None,
        "verifie": bool(poi.get("verifie")), "masque": bool(poi.get("masque")),
        "texte": (poi.get("description") if text_target == "description" else values.get("pourquoi")) or "",
        "texte_cible": text_target,
        "genre": values.get("genre") or "", "categorie": values.get("categorie") or "",
        "distinction": values.get("distinction") or "", "jours": values.get("jours") or "",
        "statut_saison": poi.get("statut_saison") or "", "months": months,
        "saison_label": season_label(poi.get("statut_saison"), months) or "",
        "type_label": labels.get(values.get("categorie")) or service_name or "",
        "fiche": {"table": table, "origine": (sheet or {}).get("origine"), "categories": labels},
        "champs": fields,
    }


def _plain(value, field: str) -> str | None:
    """Un texte court tapé par l'admin : sans balise, dans sa limite. Vide : plus de valeur."""
    value = " ".join(str(value or "").split()) if field != "texte" else str(value or "").strip()
    if re.search(r"[<>]", value):
        raise ValueError(f"{field} : pas de < ni de >")
    if len(value) > TEXT_LIMITS[field]:
        raise ValueError(f"{field} : {TEXT_LIMITS[field]} caractères au plus")
    return value or None


def typed_sheet(changes: dict, sheet: dict | None) -> tuple:
    """
    Les champs tapés, contrôlés : ({colonne de poi: valeur}, {colonne de la fiche: valeur}). Seuls les champs envoyés
    sont lus. Le nom et les liens passent par les mêmes contrôles que la relecture.
    """
    table = (sheet or {}).get("table")
    poi_fields, sheet_fields = {}, {}
    if "name" in changes:
        poi_fields["name"] = review.typed_name(changes["name"])
    if "address" in changes:
        poi_fields["address"] = _plain(changes["address"], "address")
    # Les deux liens sont facultatifs : vide, le lien est retiré. Le message dit lequel est refusé.
    try:
        if "url" in changes:
            poi_fields["url"] = review.typed_link(changes["url"]) if (changes["url"] or "").strip() else None
    except ValueError as error:
        raise ValueError(f"Lien du site : {error}") from error
    try:
        if "maps_url" in changes:
            poi_fields |= review.typed_maps_link(changes["maps_url"]) if (changes["maps_url"] or "").strip() else {"maps_url": None}
    except ValueError as error:
        raise ValueError(f"Lien Google Maps : {error}") from error
    if "statut_saison" in changes or "mois" in changes:
        status = changes.get("statut_saison") or None
        if status not in SEASONS:
            raise ValueError(f"Saison inconnue : {status}")
        months = sorted({month for month in (changes.get("mois") or []) if isinstance(month, int) and 0 <= month <= 11})
        if status == CONFIRMED_SEASON and not months:
            raise ValueError("Une saison confirmée a des mois : coche-les, ou choisis « saisonnier probable »")
        poi_fields |= {"statut_saison": status, "mois_ouverture": json.dumps(months) if status and months else None}
    if not table:
        if any(field in changes for field in ("genre", "categorie", "distinction", "jours")):
            raise ValueError("Ce lieu n'a pas de fiche d'agent : seuls le nom, l'adresse, les liens, le texte et la saison se corrigent")
    else:
        if "genre" in changes:
            sheet_fields["genre"] = _plain(changes["genre"], "genre")
            if not sheet_fields["genre"]:
                raise ValueError("Le genre ne peut pas être vide")
        if "categorie" in changes:
            if changes["categorie"] not in TABLE_LABELS[table]:
                raise ValueError(f"Type inconnu : {changes['categorie']}")
            sheet_fields["categorie"] = changes["categorie"]
        for field in ("distinction", "jours"):
            if field in changes:
                if field not in review.SHEET_COLUMNS[table]:
                    raise ValueError(f"{field} : pas pour ce lieu")
                sheet_fields[field] = _plain(changes[field], field)
    return poi_fields, sheet_fields


def _write_sheet(cursor, poi_id: int, sheet: dict, fields: dict) -> None:
    if sheet["origine"] == "table":
        assignments = ", ".join(f"{column} = %s" for column in fields)
        cursor.execute(f"UPDATE {sheet['table']} SET {assignments} WHERE poi_id = %s", (*fields.values(), poi_id))
        return
    cursor.execute("SELECT detail FROM poi_signals WHERE id = %s", (sheet["signal_id"],))
    detail = review.signal_detail(cursor.fetchone())
    detail["fiche"] = {**(detail.get("fiche") or {}), **fields}
    cursor.execute("UPDATE poi_signals SET detail = %s WHERE id = %s",
                   (json.dumps(detail, ensure_ascii=False, default=str), sheet["signal_id"]))


def _same(old, new) -> bool:
    if isinstance(old, float) or isinstance(new, float):
        return old is not None and new is not None and abs(float(old) - float(new)) < 1e-7
    return (old if old not in ("", None) else None) == (new if new not in ("", None) else None)


def decide_sheet_one(cursor, poi_id: int, changes: dict, note: str, decided_by: str, tab: str | None = None) -> list:
    """
    Applique une fiche corrigée et la trace. `tab` : la file de relecture d'où elle vient ; corriger le champ qu'elle met
    en doute la tranche (CLOSING_FIELDS). Renvoie les champs changés.
    """
    if tab is not None and tab not in review.TAB_SIGNALS:
        raise ValueError(f"File inconnue : {tab}")
    cursor.execute(f"SELECT {', '.join(review.APPLIED_COLUMNS)} FROM poi WHERE id = %s", (poi_id,))
    before = cursor.fetchone()
    if not before:
        raise ValueError(f"Lieu inconnu : {poi_id}")
    sheet = load_sheet(cursor, poi_id)
    changes = dict(changes)
    # Le texte présenté va là où l'étape 4 le lit.
    if "texte" in changes:
        text = _plain(changes.pop("texte"), "texte")
        if before.get("description") or not sheet:
            changes["__description"] = text
        else:
            changes["__pourquoi"] = text
    description = changes.pop("__description", "__absent")
    pourquoi = changes.pop("__pourquoi", "__absent")
    poi_fields, sheet_fields = typed_sheet(changes, sheet)
    if description != "__absent":
        poi_fields["description"] = description
    if pourquoi != "__absent":
        sheet_fields["pourquoi"] = pourquoi
    poi_fields = {column: value for column, value in poi_fields.items() if not _same(before.get(column), value)}
    old_sheet = (sheet or {}).get("values") or {}
    sheet_fields = {column: value for column, value in sheet_fields.items() if not _same(old_sheet.get(column), value)}
    if not poi_fields and not sheet_fields:
        raise ValueError("Rien n'a changé")
    changed = sorted({"saison" if column in ("statut_saison", "mois_ouverture") else
                      "maps_url" if column in ("latitude", "longitude") else column
                      for column in [*poi_fields, *sheet_fields]})
    signal_ids = []
    closing = CLOSING_FIELDS.get(tab)
    if closing and closing[0] in changed:
        cursor.execute("SELECT id, signal_type FROM poi_signals WHERE poi_id = %s AND statut = 'a_relire'", (poi_id,))
        signal_ids = [row["id"] for row in cursor.fetchall() if review.SIGNAL_TAB.get(row["signal_type"]) == tab]
        # Un nom trouvé à la main dit que le lieu existe : il est de nouveau affiché, comme avec « Renommer ».
        if tab == "fermetures" and before.get("masque"):
            poi_fields["masque"] = 0
    if poi_fields:
        assignments = ", ".join(f"{column} = %s" for column in poi_fields)
        cursor.execute(f"UPDATE poi SET {assignments} WHERE id = %s", (*poi_fields.values(), poi_id))
    if sheet_fields:
        _write_sheet(cursor, poi_id, sheet, sheet_fields)
    if signal_ids:
        marks = ",".join(["%s"] * len(signal_ids))
        cursor.execute(f"UPDATE poi_signals SET statut = %s, reviewed_at = NOW() WHERE id IN ({marks})",
                       (closing[1], *signal_ids))
    detail = {"file": tab or EDIT_FILE, "signal_ids": signal_ids, "champs": changed,
              "avant": {column: before[column] for column in poi_fields}}
    if sheet_fields:
        detail["avant_fiche"] = {"origine": sheet["origine"], "table": sheet["table"], "signal_id": sheet.get("signal_id"),
                                 "values": {column: old_sheet.get(column) for column in sheet_fields}}
    cursor.execute("""
        INSERT INTO decisions (objet_type, objet_id, decision, note, decided_by, decided_at, detail)
        VALUES (%s, %s, %s, %s, %s, NOW(), %s)
    """, (review.POI, poi_id, SHEET_DECISION, (note or "").strip()[:255] or None, decided_by,
          json.dumps(detail, ensure_ascii=False, default=str)))
    return changed


def decide_sheet(poi_id: int, changes: dict, note: str, decided_by: str, tab: str | None = None) -> list:
    if not isinstance(changes, dict) or not changes:
        raise ValueError("Rien à enregistrer")
    connection = MySQLUtils.connect()
    try:
        cursor = connection.cursor(dictionary=True)
        changed = decide_sheet_one(cursor, poi_id, changes, note, decided_by, tab)
        connection.commit()
        cursor.close()
        return changed
    except Exception:
        connection.rollback()
        raise
    finally:
        MySQLUtils.disconnect(connection)


def _sheet_views(cursor, poi_ids: list) -> dict:
    if not poi_ids:
        return {}
    marks = ",".join(["%s"] * len(poi_ids))
    cursor.execute(f"""
        SELECT p.id, p.latitude, p.longitude, p.masque, {', '.join(f'p.{column}' for column in POI_SHEET_COLUMNS)},
               (SELECT MIN(s.name) FROM poi_service ps JOIN services s ON s.id = ps.service_id
                WHERE ps.poi_id = p.id) AS service_name
        FROM poi p WHERE p.id IN ({marks})
    """, tuple(poi_ids))
    return {row["id"]: sheet_view(row, load_sheet(cursor, row["id"]), row["service_name"]) for row in cursor.fetchall()}


def get_sheet(poi_id: int) -> dict:
    """La fiche complète d'un lieu, pour l'ouvrir dans l'onglet « Modifier »."""
    connection = MySQLUtils.connect()
    try:
        cursor = connection.cursor(dictionary=True)
        view = _sheet_views(cursor, [poi_id]).get(poi_id)
        cursor.close()
        if not view:
            raise ValueError(f"Lieu inconnu : {poi_id}")
        return view
    finally:
        MySQLUtils.disconnect(connection)


def attach_sheets(reviews: dict) -> dict:
    """Ajoute à chaque fiche de relecture la fiche complète du lieu et ce que sa file met en doute."""
    cards = reviews.get("cards") or []
    if not cards:
        return reviews
    connection = MySQLUtils.connect()
    try:
        cursor = connection.cursor(dictionary=True)
        views = _sheet_views(cursor, list({card["poi_id"] for card in cards}))
        cursor.close()
    finally:
        MySQLUtils.disconnect(connection)
    for card in cards:
        card["fiche"] = views.get(card["poi_id"])
        card["a_verifier"] = DOUBT_FIELDS.get(card["tab"], [])
    return reviews


def human_fields(cursor, poi_id: int) -> set:
    """
    Les champs d'un lieu qu'un humain a tranchés dans la supervision et qu'un agent ne doit plus réécrire : ceux d'une
    fiche corrigée (detail.champs), et ceux des décisions de la relecture (LEGACY_FIELDS). La règle automatique ne compte pas.
    """
    cursor.execute("""
        SELECT decision, detail FROM decisions WHERE objet_type = %s AND objet_id = %s AND annulee_at IS NULL
        AND decided_by <> %s
    """, (review.POI, poi_id, review.RULE_AUTHOR))
    fields = set()
    for row in cursor.fetchall():
        if row["decision"] == SHEET_DECISION:
            fields.update(review.signal_detail(row).get("champs", []))
        elif row["decision"] in LEGACY_FIELDS:
            fields.add(LEGACY_FIELDS[row["decision"]])
    return fields
