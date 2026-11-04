"""
Enregistre ce que l'agent find_restaurants.py a trouvé.

    fiche    : une page au moins acceptée par le code, et une position. Le lieu s'affiche à l'étape 4 ;
    à relire : un lieu avec une page acceptée, mais sans position ou avec une alerte du registre, en signal
               a_confirmer, masqué s'il est nouveau ;
    écarté   : un lieu sans page acceptée. Rien n'est écrit en base, il ne reste que dans le fichier de l'agent.

Un restaurant est un POI : on réutilise la ligne d'un lieu déjà connu (même nom, ou ancien nom),
sinon on en crée une. Un lieu déjà masqué (Le Pêcheur, signalé fermé) est ignoré : il ne revient pas
dans la relecture et le code ne le démasque jamais, une décision humaine prime.
Rejouable : la fiche et les preuves d'un lieu sont remplacées, les signaux mis à jour.
"""
import json
import re
from datetime import date, datetime

from agents.find_service_links import AUTO_VERDICTS, SOCIAL_TYPES, commune_of, domain
from etl.load.load_poi import get_or_create_source, insert_histo_poi, insert_service_and_link
from etl.load.load_poi_checks import save_signal
from services.pepite_service import is_generic, match_poi, name_key
from utils.db_utils import MySQLUtils
from utils.geo_utils import geocode_address_ban, get_bounding_box, haversine_distance_km
from utils.logger_util import LoggerUtil

logger = LoggerUtil.get_logger("agent_restaurants")

SOURCE = "agent_restaurants"
SERVICE_CATEGORY = "restaurant"
MAX_KM = 15                 # au-delà, l'adresse géocodée n'est pas celle de la commune cherchée
MAX_ARTICLE_MONTHS = 18     # un article ancien ne prouve pas que le lieu existe encore
FRENCH_MONTHS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
                 "septembre", "octobre", "novembre", "décembre")
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


def _known_restaurants(cursor, city: dict) -> list:
    """Les restaurants déjà en base autour de la commune, pour réutiliser leur ligne."""
    min_lat, min_lon, max_lat, max_lon = get_bounding_box(city["latitude"], city["longitude"], MAX_KM)
    cursor.execute("""
        SELECT p.id, p.name, p.latitude, p.longitude, p.url, p.masque
        FROM poi p JOIN poi_service ps ON ps.poi_id = p.id JOIN services s ON s.id = ps.service_id
        WHERE s.category = %s AND p.latitude BETWEEN %s AND %s AND p.longitude BETWEEN %s AND %s
    """, (SERVICE_CATEGORY, min_lat, max_lat, min_lon, max_lon))
    return _rows(cursor)


def _position(city: dict, address: str | None) -> tuple | None:
    found = geocode_address_ban(address, city["latitude"], city["longitude"]) if address else None
    if found and haversine_distance_km(city["latitude"], city["longitude"], *found) <= MAX_KM:
        return found
    return None


def _find_known(row: dict, position: tuple | None, city: dict, known: list) -> dict | None:
    """La ligne du lieu : son nom d'abord, son ancien nom ensuite (Mary Stuart, devenu La Petite Folie)."""
    latitude, longitude = position or (city["latitude"], city["longitude"])
    for name in (row["nom"], row.get("ancien_nom")):
        if not name:
            continue
        same = [poi for poi in known if compact_name(poi["name"]) == compact_name(name) and not is_generic(name_key(name))]
        if same:
            return min(same, key=lambda poi: haversine_distance_km(latitude, longitude, poi["latitude"], poi["longitude"]))
        found = match_poi(name, latitude, longitude, known)
        if found:
            return found
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


def _update_poi(cursor, poi: dict, row: dict, position: tuple | None) -> None:
    """L'adresse et la position de l'agent sont meilleures qu'OSM ; un lien déjà connu est gardé."""
    fields = {"url": poi["url"] or row.get("lien"), "address": row.get("adresse")}
    if position:
        fields |= {"latitude": position[0], "longitude": position[1]}
    if row.get("ancien_nom") and name_key(poi["name"]) == name_key(row["ancien_nom"]):
        fields["name"] = row["nom"]
    assignments = ", ".join(f"{column} = %s" for column in fields)
    cursor.execute(f"UPDATE poi SET {assignments} WHERE id = %s", (*fields.values(), poi["id"]))


def _save_season(cursor, poi_id: int, row: dict) -> None:
    """La saison contrôlée, et rien sinon, sauf si un humain l'a déjà tranchée : sa décision prime."""
    cursor.execute("""
        SELECT 1 FROM decisions WHERE objet_type = 'poi' AND objet_id = %s AND annulee_at IS NULL
        AND decision IN ('valider_saison', 'pas_saisonnier')
    """, (poi_id,))
    if cursor.fetchone():
        return
    if not row.get("saisonnier"):
        cursor.execute("UPDATE poi SET statut_saison = NULL, mois_ouverture = NULL WHERE id = %s", (poi_id,))
        return
    months = parse_months(row.get("mois_ouverture"))
    cursor.execute("UPDATE poi SET statut_saison = %s, mois_ouverture = %s WHERE id = %s",
                   ("confirmee" if months else "probable", json.dumps(months) if months else None, poi_id))


def _save_sheet(cursor, poi_id: int, row: dict, version: int, model: str) -> None:
    cursor.execute("""
        REPLACE INTO restaurants (poi_id, genre, pourquoi, budget, jours_fermeture, distinction, ancien_nom,
                                  prompt_version, model, trouve_le)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (poi_id, row["genre"][:100], row.get("pourquoi"), (row.get("budget") or "")[:50] or None,
          (row.get("jours_fermeture") or "")[:150] or None, (row.get("distinction") or "")[:100] or None,
          row.get("ancien_nom"), version, model, datetime.now()))


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


def _flag(cursor, row: dict, position: tuple | None, city: dict, known: list, source_id: int, reason: str, detail: dict) -> None:
    """À confirmer : sur la ligne du lieu s'il est connu, sinon sur une nouvelle ligne masquée."""
    poi = _find_known(row, position, city, known)
    if poi and poi["masque"]:
        return
    poi_id = poi["id"] if poi else _create_poi(cursor, {**row, "lien": None}, position, city, source_id, masked=True)
    cursor.execute("SELECT 1 FROM restaurants WHERE poi_id = %s", (poi_id,))
    if not cursor.fetchone():
        save_signal(cursor, poi_id, SOURCE, "a_confirmer", {"raison": reason, "adresse": row.get("adresse"), **detail})


def review_reason(row: dict, located) -> str | None:
    """Pourquoi ce lieu, qui a une page acceptée, doit attendre une relecture au lieu d'être montré, ou None."""
    if row.get("alerte_registre"):
        return f"registre : {row['alerte_registre']}"
    return None if located else "position introuvable"


def save_commune(city: dict, answer: dict, version: int, model: str) -> dict:
    """Enregistre une commune en une transaction. Renvoie le nombre de fiches, de lieux à relire et de lieux écartés."""
    summary = {"fiches": 0, "a_confirmer": 0, "sans_page": 0}
    sheets = set()
    connection = MySQLUtils.connect()
    try:
        cursor = connection.cursor()
        source_id = get_or_create_source(cursor, SOURCE)
        known = _known_restaurants(cursor, city)
        for row in answer["restaurants"]:
            position = _position(city, row.get("adresse"))
            poi = _find_known(row, position, city, known)
            if poi and poi["masque"]:
                continue
            accepted = [page for page in row["pages"] if page_accepted(page, commune=city["name"])]
            if not accepted:
                logger.info(f"[restaurants] {city['name']} : {row['nom']} écarté, aucune page acceptée")
                summary["sans_page"] += 1
                continue
            reason = review_reason(row, position or poi)
            if reason:
                _flag(cursor, row, position, city, known, source_id, reason,
                      {"indice": row.get("pourquoi"), "page": row.get("lien"),
                       "verdicts": [page.get("verdict") for page in row["pages"]]})
                summary["a_confirmer"] += 1
                continue
            # Le lien montré au voyageur est toujours une page acceptée.
            row = {**row, "lien": accepted[0]["url"]}
            if poi:
                _update_poi(cursor, poi, row, position)
                poi_id = poi["id"]
            else:
                poi_id = _create_poi(cursor, row, position, city, source_id, masked=False)
            _save_season(cursor, poi_id, row)
            _save_sheet(cursor, poi_id, row, version, model)
            _save_proofs(cursor, poi_id, row["pages"])
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
