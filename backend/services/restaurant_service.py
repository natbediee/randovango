"""
Enregistre ce que l'agent find_restaurants.py a trouvé.

    fiche    : le registre ou une page acceptée montre un restaurant à l'adresse, et on a une position. Le lieu s'affiche à l'étape 4 ;
    à relire : un tel lieu, mais sans position ou avec une enseigne fermée au registre, en signal a_confirmer, masqué s'il est nouveau ;
               de même, avec ou sans page, un lieu que l'agent n'a pas pu trancher (row["a_relire"]) : preuve sans réponse
               à temps, ou bar au registre dit servir des repas ;
    écarté   : ni registre ni page acceptée, ou une liquidation judiciaire. Rien n'est écrit en base, il ne reste que dans le fichier de l'agent.

Un restaurant est un POI : on réutilise la ligne d'un lieu déjà connu (même nom, ou ancien nom),
sinon on en crée une. Un lieu déjà masqué (Le Pêcheur, signalé fermé) est ignoré : il ne revient pas
dans la relecture et le code ne le démasque jamais, une décision humaine prime.
Rejouable : la fiche et les preuves d'un lieu sont remplacées, les signaux mis à jour.
"""
import json
import re
from datetime import date, datetime

from agents.find_service_links import AUTO_VERDICTS, SOCIAL_TYPES, TYPE_RANK, commune_of, domain
from etl.load.load_poi import get_or_create_source, insert_histo_poi, insert_service_and_link
from etl.load.load_poi_checks import save_signal
from services.pepite_service import is_generic, match_poi, name_key
from utils.db_utils import MySQLUtils
from utils.display_utils import HIDDEN_SPOT_TYPES
from utils.geo_utils import geocode_address_ban, geocode_locality_ban, get_bounding_box, haversine_distance_km
from utils.logger_util import LoggerUtil

logger = LoggerUtil.get_logger("agent_restaurants")

SOURCE = "agent_restaurants"
SERVICE_CATEGORY = "restaurant"
MAX_KM = 15                 # au-delà, l'adresse géocodée n'est pas celle de la commune cherchée
SAME_PLACE_KM = 0.05        # même nom, sans numéro de rue : à moins de 50 m, c'est le même lieu
RULE_AUTHOR = "règle automatique"   # les décisions de la règle (poi_triage_service.py) ne bloquent pas l'agent
HUMAN_NAME_DECISIONS = ("renommer", "autre_nom", "valider_lien_nom")
HUMAN_LINK_DECISIONS = ("valider_lien", "valider_lien_nom", "refuser_lien", "autre_lien", "retirer_lien", "garder_lien")
SHEET_FIELDS = ("genre", "pourquoi", "distinction", "ancien_nom", "categorie", "registre_depuis")
OLD_NAME_KM = 1             # un ancien nom ne retrouve un lieu connu qu'à cette distance de l'adresse (Cléder : 0,51 km pour le même lieu)
MAX_ARTICLE_MONTHS = 18     # un article ancien ne prouve pas que le lieu existe encore
FRENCH_MONTHS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
                 "septembre", "octobre", "novembre", "décembre")
COMMON_STREET_WORDS = {"rue", "route", "boulevard", "bd", "avenue", "av", "place", "quai", "chemin", "impasse", "allee", "lieudit", "lieu", "dit",
                       "ld", "de", "du", "des", "la", "le", "les", "l", "d"}
_MONTH_RANGE = re.compile(rf"({'|'.join(FRENCH_MONTHS)})\s+à\s+({'|'.join(FRENCH_MONTHS)})", re.I)


def commune_of_address(address: str | None, default: str) -> tuple:
    """(commune, code postal) de l'adresse, sinon la commune cherchée."""
    commune, postcode = commune_of(address)
    return (commune, postcode) if commune else (default, None)


def parse_months(text: str | None) -> list:
    """« avril à septembre » -> [3, ..., 8], le format de poi.mois_ouverture. Vide si illisible."""
    match = _MONTH_RANGE.search(text or "")
    if not match:
        return []
    first, last = (FRENCH_MONTHS.index(month.lower()) for month in match.groups())
    return [(first + step) % 12 for step in range((last - first) % 12 + 1)]


def page_date(text: str | None) -> date | None:
    """« 2026-07 » -> le 1er juillet 2026 : l'agent ne donne souvent que l'année et le mois."""
    match = re.fullmatch(r"(\d{4})-(\d{2})(?:-\d{2})?", (text or "").strip())
    if not match or not 1 <= int(match.group(2)) <= 12:
        return None
    return date(int(match.group(1)), int(match.group(2)), 1)


def compact_name(name: str) -> str:
    """Le nom sans espaces : « Ti Madeo » et « Ti Mad Eo » sont le même lieu."""
    return name_key(name).replace(" ", "")


def place_key(name: str) -> str:
    """« La Crêperie Riboul » et « Riboul », « Spiaggia Restaurant » et « Spiaggia » sont le même lieu d'un passage à l'autre."""
    words = [word for word in name_key(name).split() if word not in ("creperie", "restaurant")]
    # « La Crêperie du Château d'Eau » au registre est « Le Château d'Eau » des recherches (Ploudalmézeau, 7 novembre 2026).
    while words and words[0] in ("l", "la", "le", "les", "d", "de", "du", "des"):
        words.pop(0)
    return "".join(words) or compact_name(name)


def street_words(address: str | None) -> list:
    """Les mots de l'adresse, sans le code postal ni ce qui le suit, et sans les mots communs à toutes les rues."""
    street = re.split(r"\b\d{5}\b", address or "")[0]
    return [word for word in name_key(street).split() if word not in COMMON_STREET_WORDS]


def same_address(first: str | None, second: str | None) -> bool:
    """Même numéro et même rue. Sans numéro, on ne conclut pas : le boulevard de la Mer compte plusieurs tables."""
    words, others = street_words(first), street_words(second)
    number = next((word for word in words if word.isdigit()), None)
    if not number or number != next((word for word in others if word.isdigit()), None):
        return False
    street, other_street = {word for word in words if not word.isdigit()}, {word for word in others if not word.isdigit()}
    return bool(street and other_street) and len(street & other_street) / min(len(street), len(other_street)) >= 0.5


def is_town_hall(url: str, commune: str) -> bool:
    """
    Le site d'une mairie : plougonvelin.fr cite encore Kan Ar Mor, reprise depuis. Le domaine est le nom
    de la commune, et rien d'autre : lacabaneplougonvelin.com ou crozon-tourisme.bzh ne sont pas des mairies.
    """
    host = domain(url)
    return host.startswith(("mairie", "ville-")) or compact_name(host.rsplit(".", 1)[0]) == compact_name(commune)


def page_accepted(page: dict, today: date = None, commune: str = "") -> bool:
    """Une page acceptée par le code, hors mairie, agrégateur et réseau social. Un article doit en plus être daté et récent."""
    if page.get("verdict") not in AUTO_VERDICTS or page["type_page"] in ("mairie", "agregateur", *SOCIAL_TYPES):
        return False
    if any(site in domain(page.get("url") or "").split(".") for site in SOCIAL_TYPES):
        return False
    if commune and is_town_hall(page["url"], commune):
        return False
    if page["type_page"] != "presse":
        return True
    published = page_date(page.get("date_page"))
    today = today or date.today()
    return bool(published) and (today.year - published.year) * 12 + today.month - published.month <= MAX_ARTICLE_MONTHS


def _rows(cursor) -> list:
    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def load_city(name: str) -> dict | None:
    connection = MySQLUtils.connect()
    cursor = connection.cursor()
    cursor.execute("SELECT id, name, latitude, longitude, department FROM cities WHERE name = %s", (name,))
    rows = _rows(cursor)
    cursor.close()
    MySQLUtils.disconnect(connection)
    return rows[0] if rows else None


def commune_spots(name: str) -> list:
    """
    Les spots proposables dont l'adresse est dans la commune : ils découpent une grande ville en zones de recherche.
    L'adresse, pas la distance au centre : celui de Brest est à Sainte-Anne du Portzic, à 9,6 km de ses derniers spots.
    """
    placeholders = ",".join(["%s"] * len(HIDDEN_SPOT_TYPES))
    connection = MySQLUtils.connect()
    cursor = connection.cursor()
    cursor.execute(f"""SELECT id, latitude, longitude, address, city_label FROM spots
                       WHERE (city_label = %s OR address LIKE %s) AND type IS NOT NULL AND type NOT IN ({placeholders})
                         AND duplicate_of_spot_id IS NULL AND p4n_removed = 0 AND (nuit_interdite IS NULL OR nuit_interdite = 0)
                       ORDER BY id""", (name, f"%{name}", *HIDDEN_SPOT_TYPES))
    rows = _rows(cursor)
    cursor.close()
    MySQLUtils.disconnect(connection)
    in_commune = re.compile(rf"\b\d{{5}}\s+{re.escape(name)}$", re.I)
    return [row for row in rows if row["city_label"] == name or in_commune.search(row["address"] or "")]


def _known_restaurants(cursor, city: dict) -> list:
    """Les restaurants déjà en base autour de la commune, pour réutiliser leur ligne."""
    min_lat, min_lon, max_lat, max_lon = get_bounding_box(city["latitude"], city["longitude"], MAX_KM)
    cursor.execute("""
        SELECT p.id, p.name, p.address, p.latitude, p.longitude, p.url, p.masque
        FROM poi p JOIN poi_service ps ON ps.poi_id = p.id JOIN services s ON s.id = ps.service_id
        WHERE s.category = %s AND p.latitude BETWEEN %s AND %s AND p.longitude BETWEEN %s AND %s
    """, (SERVICE_CATEGORY, min_lat, max_lat, min_lon, max_lon))
    return _rows(cursor)


def _position(city: dict, address: str | None) -> tuple | None:
    """
    La position de l'adresse, à la rue près, sinon celle de son lieu-dit (une ferme, une crêperie de campagne : la
    moitié des « position introuvable » à relire le 7 novembre 2026). Rien si elle est loin de la commune cherchée.
    """
    if not address:
        return None
    for geocode in (geocode_address_ban, geocode_locality_ban):
        found = geocode(address, city["latitude"], city["longitude"])
        if found and haversine_distance_km(city["latitude"], city["longitude"], *found) <= MAX_KM:
            return found
    return None


def _find_known(row: dict, position: tuple | None, city: dict, known: list) -> dict | None:
    """
    La ligne du lieu : son nom d'abord, son ancien nom ensuite (Mary Stuart, devenu La Petite Folie). L'ancien nom ne
    vaut qu'à l'adresse même : « Le Triskell », ancien nom du Neuf à Ploudalmézeau, désignait aussi un restaurant à
    10 km, et Le Neuf a été perdu (7 novembre 2026). Sans position, on ne cherche pas par l'ancien nom.
    """
    latitude, longitude = position or (city["latitude"], city["longitude"])
    for name in (row["nom"], row.get("ancien_nom")):
        if not name:
            continue
        candidates = known
        if name != row["nom"]:
            if not position:
                continue
            candidates = [poi for poi in known if poi["latitude"] is not None
                          and haversine_distance_km(latitude, longitude, poi["latitude"], poi["longitude"]) <= OLD_NAME_KM]
        same = [poi for poi in candidates if compact_name(poi["name"]) == compact_name(name) and not is_generic(name_key(name))]
        if same:
            return min(same, key=lambda poi: haversine_distance_km(latitude, longitude, poi["latitude"], poi["longitude"]))
        found = match_poi(name, latitude, longitude, candidates)
        if found:
            return found
    return _same_place(row, position, known)


def _same_place(row: dict, position: tuple | None, known: list) -> dict | None:
    """
    Le même lieu sous un autre nom de la même table : « Racines » et « Restaurant Racines » au même numéro de Crozon,
    « Crêperie La Chaumine » et « La Chaumine Biligou ». Sur 992 pépites, 10 doublons de ce genre (7 novembre 2026).
    Il faut le nom ET le lieu : l'Hostellerie et le Bistrot 1954 partagent une adresse et sont deux tables.
        - même adresse (numéro et rue), et l'un des deux noms contient l'autre ;
        - sans numéro (« Saint-Roch »), le même nom et la même position à SAME_PLACE_KM près.
    """
    key = place_key(row["nom"])
    if len(key) < 4:
        return None
    for poi in known:
        other = place_key(poi["name"])
        if len(other) < 4:
            continue
        if (key in other or other in key) and same_address(row.get("adresse"), poi.get("address")):
            return poi
        if key == other and position and poi["latitude"] is not None \
                and haversine_distance_km(*position, poi["latitude"], poi["longitude"]) <= SAME_PLACE_KM:
            return poi
    return None


def _create_poi(cursor, row: dict, position: tuple | None, city: dict, source_id: int, masked: bool) -> int:
    latitude, longitude = position or (None, None)
    cursor.execute(
        "INSERT INTO poi (name, latitude, longitude, url, address, source_id, verifie, masque)"
        " VALUES (%s, %s, %s, %s, %s, %s, 0, %s)",
        (row["nom"], latitude, longitude, row.get("lien"), row.get("adresse"), source_id, int(masked)))
    poi_id = cursor.lastrowid
    insert_histo_poi(cursor, poi_id, city["name"])
    insert_service_and_link(cursor, poi_id, SERVICE_CATEGORY)
    return poi_id


def _decided_by_human(cursor, poi_id: int, decisions: tuple) -> bool:
    """Un humain a tranché ce point du lieu dans la supervision (poi_review_service.py) : sa décision prime sur l'agent."""
    marks = ", ".join(["%s"] * len(decisions))
    cursor.execute(f"""
        SELECT 1 FROM decisions WHERE objet_type = 'poi' AND objet_id = %s AND annulee_at IS NULL
        AND decided_by <> %s AND decision IN ({marks}) LIMIT 1
    """, (poi_id, RULE_AUTHOR, *decisions))
    return cursor.fetchone() is not None


class _DictRows:
    """Un curseur qui rend des dictionnaires, comme celui qu'attend poi_edit_service, à partir de celui d'un agent."""

    def __init__(self, cursor):
        self.cursor = cursor

    def execute(self, sql, params=None):
        self.cursor.execute(sql, params)

    def fetchall(self):
        rows = self.cursor.fetchall()
        if not rows or isinstance(rows[0], dict):
            return rows
        columns = [column[0] for column in self.cursor.description]
        return [dict(zip(columns, row)) for row in rows]


def human_fields(cursor, poi_id: int) -> set:
    """
    Les champs qu'un humain a corrigés dans la supervision (onglet « Modifier », poi_edit_service.human_fields) : un
    passage d'agent les laisse tels quels (8 novembre 2026). Noms : name, address, url, maps_url (position comprise),
    description, saison (statut et mois), et genre, pourquoi, categorie, jours, distinction pour la fiche.
    """
    from services import poi_edit_service   # ici : poi_edit_service importe ce module
    return poi_edit_service.human_fields(_DictRows(cursor), poi_id)


def keep_human_sheet(cursor, table: str, poi_id: int, row: dict, columns: tuple) -> dict:
    """La fiche de l'agent, avec les valeurs déjà en base pour les champs qu'un humain a corrigés."""
    kept = sorted(human_fields(cursor, poi_id) & set(columns))
    if not kept:
        return row
    cursor.execute(f"SELECT {', '.join(kept)} FROM {table} WHERE poi_id = %s", (poi_id,))
    old = cursor.fetchone()
    if not old:
        return row
    return {**row, **(old if isinstance(old, dict) else dict(zip(kept, old)))}


def _update_poi(cursor, poi: dict, row: dict, position: tuple | None) -> None:
    """
    L'adresse et la position de l'agent sont meilleures qu'OSM, et son lien est une page acceptée : l'ancien pouvait être
    Facebook. Un lien ou un nom tranché par un humain dans la supervision n'est plus touché (7 novembre 2026), ni rien
    de ce qu'il a corrigé dans l'onglet « Modifier » (8 novembre 2026) : un lien Google Maps saisi fixe aussi la position.
    """
    human = human_fields(cursor, poi["id"])
    fields = {} if "address" in human else {"address": row.get("adresse")}
    if row.get("lien") and "url" not in human and not _decided_by_human(cursor, poi["id"], HUMAN_LINK_DECISIONS):
        fields["url"] = row["lien"]
    if position and "maps_url" not in human:
        fields |= {"latitude": position[0], "longitude": position[1]}
    if row.get("ancien_nom") and name_key(poi["name"]) == name_key(row["ancien_nom"]) \
            and "name" not in human and not _decided_by_human(cursor, poi["id"], HUMAN_NAME_DECISIONS):
        fields["name"] = row["nom"]
    if poi.get("masque"):
        fields["masque"] = 0     # la ligne masquée en attendant la relecture s'affiche avec sa fiche
    if not fields:
        return
    assignments = ", ".join(f"{column} = %s" for column in fields)
    cursor.execute(f"UPDATE poi SET {assignments} WHERE id = %s", (*fields.values(), poi["id"]))


def _save_season(cursor, poi_id: int, row: dict) -> None:
    """La saison contrôlée, et rien sinon, sauf si un humain l'a déjà tranchée : sa décision prime."""
    cursor.execute("""
        SELECT 1 FROM decisions WHERE objet_type = 'poi' AND objet_id = %s AND annulee_at IS NULL
        AND decision IN ('valider_saison', 'pas_saisonnier')
    """, (poi_id,))
    if cursor.fetchone() or "saison" in human_fields(cursor, poi_id):
        return
    if not row.get("saisonnier"):
        cursor.execute("UPDATE poi SET statut_saison = NULL, mois_ouverture = NULL WHERE id = %s", (poi_id,))
        return
    months = parse_months(row.get("mois_ouverture"))
    cursor.execute("UPDATE poi SET statut_saison = %s, mois_ouverture = %s WHERE id = %s",
                   ("confirmee" if months else "probable", json.dumps(months) if months else None, poi_id))


def set_verified(cursor, poi_id: int, verified: bool) -> None:
    """
    Le badge « Vérifié » suit la preuve (7 novembre 2026) : une page acceptée par le code nomme le lieu, ou un humain l'a
    validé. Avant, il disait seulement d'où venait la ligne : 1 pour tout POI d'OSM (load_poi.py), 0 pour ceux de l'agent.
    Un lieu gardé par le registre seul reste « Non vérifié » : le registre montre une activité, pas le nom (Leonetti).
    """
    cursor.execute("UPDATE poi SET verifie = %s WHERE id = %s", (int(verified), poi_id))


def sheet_of(row: dict, version: int, model: str) -> dict:
    """Ce qu'il faut pour écrire la fiche plus tard, si un humain valide le lieu à confirmer (poi_review_service.py)."""
    return {**{field: row.get(field) for field in SHEET_FIELDS}, "prompt_version": version, "model": model}


def save_validated_sheet(cursor, poi_id: int, sheet: dict) -> None:
    """La fiche d'un lieu à confirmer qu'un humain a validé : celle que l'agent avait préparée."""
    if not sheet or not sheet.get("genre"):
        raise ValueError("Ce lieu n'a pas de fiche préparée par l'agent : il faut le relancer")
    _save_sheet(cursor, poi_id, sheet, sheet.get("prompt_version"), sheet.get("model"))
    set_verified(cursor, poi_id, True)


def _save_sheet(cursor, poi_id: int, row: dict, version: int, model: str) -> None:
    row = keep_human_sheet(cursor, "restaurants", poi_id, row, ("genre", "pourquoi", "distinction", "categorie"))
    cursor.execute("""
        REPLACE INTO restaurants (poi_id, genre, pourquoi, distinction, ancien_nom, categorie, registre_depuis,
                                  prompt_version, model, trouve_le)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (poi_id, row["genre"][:100], row.get("pourquoi"), (row.get("distinction") or "")[:100] or None,
          row.get("ancien_nom"), row.get("categorie"), row.get("registre_depuis"), version, model, datetime.now()))


def _save_proofs(cursor, poi_id: int, pages: list) -> None:
    cursor.execute("DELETE FROM poi_preuves WHERE poi_id = %s", (poi_id,))
    for page in pages:
        found = page.get("citation_trouvee")
        cursor.execute("""
            INSERT INTO poi_preuves (poi_id, url, type_page, porte_sur, citation, citation_trouvee, date_page,
                                     periode_affichee, verdict, controle_le)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (poi_id, page["url"][:512], page["type_page"], page.get("porte_sur"), page.get("citation"), None if found is None else int(found),
              page_date(page.get("date_page")), (page.get("periode_affichee") or "")[:255] or None,
              page["verdict"], datetime.now()))


def waiting_for_review(cursor, poi_id: int, source: str) -> bool:
    """La ligne attend la relecture de cet agent : c'est lui qui l'a masquée (_flag), pas un humain."""
    cursor.execute("""SELECT 1 FROM poi_signals WHERE poi_id = %s AND source = %s AND signal_type = 'a_confirmer'
                      AND statut = 'a_relire' LIMIT 1""", (poi_id, source))
    return cursor.fetchone() is not None


def best_link(accepted: list) -> str | None:
    """Le lien gardé : toujours une page acceptée, son site si on l'a, et rien sinon."""
    best = min(accepted, key=lambda page: TYPE_RANK.get(page["type_page"], len(TYPE_RANK)), default=None)
    return best["url"] if best else None


def alert_contradicted(row: dict, register: dict | None) -> bool:
    """
    L'alerte de l'analyste est contredite par le registre lui-même : un établissement actif au même nom et à la même
    adresse. A Fleur d'Eau (Douarnenez) : enseigne de l'ancien exploitant fermée le 1er juillet 2025, celle du nouveau
    active depuis le 15 mai 2025 ; l'analyste avait écrit « sans établissement actif du même nom » (8 novembre 2026).
    Une liquidation n'est jamais effacée.
    """
    if not row.get("alerte_registre") or is_liquidated(row):
        return False
    return any(line.get("nom") and place_key(line["nom"]) == place_key(row["nom"])
               and same_address(row.get("adresse"), line.get("adresse"))
               for line in (register or {}).get("actifs", []))


def clear_contradicted_alerts(rows: list, register: dict | None, commune: str, label: str) -> None:
    for row in rows:
        if alert_contradicted(row, register):
            logger.info(f"[{label}] {commune} : alerte de {row['nom']} effacée, le registre a un établissement actif"
                        f" à ce nom et à cette adresse ({row['alerte_registre']})")
            row["alerte_registre"] = None


def _flag(cursor, row: dict, position: tuple | None, city: dict, known: list, source_id: int, reason: str, detail: dict,
          link: str | None = None) -> None:
    """
    À confirmer : sur la ligne du lieu s'il est connu, sinon sur une nouvelle ligne masquée, avec la page acceptée
    (link) : confirmer le lieu l'affiche avec son lien (8 novembre 2026, A Fleur d'Eau s'affichait sans son site).
    """
    poi = _find_known(row, position, city, known)
    if poi and poi["masque"]:
        return
    poi_id = poi["id"] if poi else _create_poi(cursor, {**row, "lien": link}, position, city, source_id, masked=True)
    cursor.execute("SELECT 1 FROM restaurants WHERE poi_id = %s", (poi_id,))
    if not cursor.fetchone():
        save_signal(cursor, poi_id, SOURCE, "a_confirmer", {"raison": reason, "adresse": row.get("adresse"), **detail})


def is_liquidated(row: dict) -> bool:
    """Une liquidation judiciaire au registre retire le lieu sans relecture (décision du 5 novembre 2026)."""
    return "liquidation" in name_key(row.get("alerte_registre") or "")


def review_reason(row: dict, located) -> str | None:
    """Pourquoi ce lieu doit attendre une relecture au lieu d'être montré, ou None."""
    if row.get("a_relire"):
        return row["a_relire"]
    if row.get("alerte_registre"):
        return f"registre : {row['alerte_registre']}"
    return None if located else "position introuvable"


def save_commune(city: dict, answer: dict, version: int, model: str) -> dict:
    """Enregistre une commune en une transaction. Renvoie le nombre de fiches, de lieux à relire et de lieux écartés."""
    summary = {"fiches": 0, "a_confirmer": 0, "sans_page": 0, "liquidation": 0}
    sheets = set()
    connection = MySQLUtils.connect()
    try:
        cursor = connection.cursor()
        source_id = get_or_create_source(cursor, SOURCE)
        known = _known_restaurants(cursor, city)
        for row in answer["restaurants"]:
            position = _position(city, row.get("adresse"))
            poi = _find_known(row, position, city, known)
            # Une ligne masquée par un humain ou une décision reste à l'écart ; celle que l'agent a masquée en attendant
            # la relecture se reprend (8 novembre 2026 : A Fleur d'Eau et Episervice restaient bloqués).
            if poi and poi["masque"] and not waiting_for_review(cursor, poi["id"], SOURCE):
                continue
            if is_liquidated(row):
                logger.info(f"[restaurants] {city['name']} : {row['nom']} écarté, {row['alerte_registre']}")
                summary["liquidation"] += 1
                continue
            accepted = [page for page in row["pages"] if page_accepted(page, commune=city["name"])]
            if not accepted and not row.get("au_registre") and not row.get("a_relire"):
                logger.info(f"[restaurants] {city['name']} : {row['nom']} écarté, ni registre ni page acceptée")
                summary["sans_page"] += 1
                continue
            reason = review_reason(row, position or poi)
            if reason:
                _flag(cursor, row, position, city, known, source_id, reason,
                      {"indice": row.get("pourquoi"), "page": row.get("lien"),
                       "verdicts": [page.get("verdict") for page in row["pages"]], "fiche": sheet_of(row, version, model)},
                      link=best_link(accepted))
                summary["a_confirmer"] += 1
                continue
            row = {**row, "lien": best_link(accepted)}
            if poi:
                _update_poi(cursor, poi, row, position)
                poi_id = poi["id"]
            else:
                poi_id = _create_poi(cursor, row, position, city, source_id, masked=False)
            _save_season(cursor, poi_id, row)
            _save_sheet(cursor, poi_id, row, version, model)
            _save_proofs(cursor, poi_id, row["pages"])
            set_verified(cursor, poi_id, bool(accepted))
            # Le lieu a maintenant sa fiche : il n'attend plus de relecture.
            cursor.execute("DELETE FROM poi_signals WHERE poi_id = %s AND source = %s AND signal_type = 'a_confirmer'",
                           (poi_id, SOURCE))
            sheets.add(poi_id)
        summary["fiches"] = len(sheets)
        connection.commit()
        cursor.close()
    except Exception:
        connection.rollback()
        raise
    finally:
        MySQLUtils.disconnect(connection)
    logger.info(f"[restaurants] {city['name']} : {summary}")
    return summary
