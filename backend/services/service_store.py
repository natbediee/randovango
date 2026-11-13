"""
L'enregistrement des services trouvés par les agents (agents/service_chain.py) : une seule façon d'écrire une commune en
base, réglée par catégorie (agents/service_category.py). Une règle corrigée ici l'est pour toutes les catégories.

CE QUE DEVIENT CHAQUE LIEU D'UNE RÉPONSE (save_commune)
    fiche    : le registre ou une page acceptée le montre, et on a une position. Il s'affiche à l'étape 4 ;
    à relire : un tel lieu, mais sans position, avec une alerte du registre, ou que l'agent n'a pas pu trancher
               (row["a_relire"] : preuve sans réponse à temps, bar au registre dit servir des repas, registre seul) :
               signal a_confirmer, sur une ligne masquée s'il est nouveau. Le signal garde la fiche préparée : la valider
               dans /supervision l'enregistre (save_validated_sheet) ;
    écarté   : ni registre ni page acceptée, ou une liquidation judiciaire. Rien n'est écrit en base, il ne reste que
               dans le fichier de l'agent.

Un service est un POI : on réutilise la ligne d'un lieu déjà connu (même nom ou ancien nom, au même endroit), quel que
soit son service, et on l'enrichit ; sinon on en crée une.
Un lieu déjà masqué (Le Pêcheur, signalé fermé) est ignoré : il ne revient pas dans la relecture et le code ne le
démasque jamais, une décision humaine prime.
Rejouable : la fiche et les preuves d'un lieu sont remplacées, les signaux mis à jour.

Ce fichier porte aussi ce que les deux bouts de la chaîne partagent : la clé d'un nom, la comparaison de deux adresses,
la règle d'une page acceptée, et le choix de la ville d'où chercher une commune.
"""
import json
import re
from datetime import date, datetime
from urllib.parse import urlparse

from agents.find_service_links import AUTO_VERDICTS, SOCIAL_TYPES, TYPE_RANK, commune_of, domain
from etl.load.load_poi import get_or_create_source, insert_histo_poi, insert_service_and_link
from etl.load.load_poi_checks import save_signal
from services.pepite_service import is_generic, name_key
from utils.db_utils import MySQLUtils
from utils.display_utils import HIDDEN_SPOT_TYPES
from utils.geo_utils import (city_commune, geocode_address_ban, geocode_locality_ban, geocode_sure_address_ban, geocode_way_ban,
                             get_bounding_box, haversine_distance_km)
from utils.service_utils import POI_FRONTEND_CATEGORY_MAP

MAX_KM = 15                 # au-delà, l'adresse géocodée n'est pas celle de la commune cherchée
SAME_PLACE_KM = 0.05        # même nom, sans numéro de rue : à moins de 50 m, c'est le même lieu
RULE_AUTHOR = "règle automatique"   # les décisions de la règle (poi_triage_service.py) ne bloquent pas l'agent
HUMAN_NAME_DECISIONS = ("renommer", "autre_nom", "valider_lien_nom")
HUMAN_LINK_DECISIONS = ("valider_lien", "valider_lien_nom", "refuser_lien", "autre_lien", "retirer_lien", "garder_lien")
# UN AGENT ENRICHIT, IL NE RECRÉE PAS (11 novembre 2026). Le lieu déjà en base est cherché dans tous les services des
# onglets que la chaîne remplit, quelle que soit la catégorie qui passe : Le Galion de Ploudalmézeau existait deux fois,
# restaurant pour un agent et café pour l'autre, parce que chacun ne regardait que ses propres services.
KNOWN_TABS = ("restauration", "cafe", "commerce", "supermarche")
KNOWN_SERVICES = tuple(service for service, tab in POI_FRONTEND_CATEGORY_MAP.items() if tab in KNOWN_TABS)
# Le signal d'un doublon possible, à trancher dans la file « Doublons » de /supervision (poi_duplicates_service.py).
DUPLICATE_SOURCE, DUPLICATE_SIGNAL = "doublons", "doublon_service"
NO_POSITION = "position introuvable"    # la raison d'une relecture quand l'adresse n'a pas pu être placée (review_reason)
SAME_NAME_KM = 1            # un nom, actuel ou ancien, ne retrouve un lieu connu qu'à cette distance (find_in)
COMMUNE_KM = 5              # sans code postal à comparer, un lieu est dans la commune à cette distance de son centre
MAX_ARTICLE_MONTHS = 18     # un article ancien ne prouve pas que le lieu existe encore
FRENCH_MONTHS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
                 "septembre", "octobre", "novembre", "décembre")
COMMON_STREET_WORDS = {"rue", "route", "boulevard", "bd", "avenue", "av", "place", "quai", "chemin", "impasse", "allee", "lieudit", "lieu", "dit",
                       "ld", "de", "du", "des", "la", "le", "les", "l", "d"}
ARTICLES = ("l", "la", "le", "les", "d", "de", "du", "des")
# Les mots qui disent ce qu'est un lieu, pas lequel, rangés par famille : deux mots de la même famille ne se contredisent
# pas (« bar » et « café »), deux mots de familles différentes désignent deux lieux (« marché » et « épicerie »).
PLACE_KINDS = {"creperie": "table", "restaurant": "table", "cafe": "cafe", "bar": "cafe",
               "boulangerie": "boulangerie", "patisserie": "boulangerie", "epicerie": "epicerie", "superette": "epicerie",
               "marche": "marche", "ferme": "ferme", "fromagerie": "fromagerie", "boucherie": "boucherie",
               "poissonnerie": "poissonnerie", "cave": "cave"}
_MONTH_RANGE = re.compile(rf"({'|'.join(FRENCH_MONTHS)})\s+à\s+({'|'.join(FRENCH_MONTHS)})", re.I)


# --- Les noms, les adresses et les pages ---

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
    """
    Le nom sans le mot qui dit ce qu'est le lieu, ni l'article en tête : « La Crêperie Riboul » et « Riboul », « Boulangerie
    Le Gall » et « Le Gall », « La Crêperie du Château d'Eau » du registre et « Le Château d'Eau » des recherches
    (Ploudalmézeau, 7 novembre 2026). À comparer avec same_name, jamais seule : « Marché de Plougonvelin » et « Épicerie de
    Plougonvelin » ont la même clé.
    """
    def without_articles(words: list) -> list:
        while words and words[0] in ARTICLES:
            words = words[1:]
        return words

    words = name_key(name).split()
    # « Le Café du Marché » n'est fait que de ces mots : ils restent, sinon il ne resterait rien.
    return "".join(without_articles([word for word in words if word not in PLACE_KINDS]) or without_articles(words))


def place_kinds(name: str) -> set:
    """Ce que le nom dit du lieu : {"cafe"} pour « Bar du Port », rien pour « Le Galion »."""
    return {PLACE_KINDS[word] for word in name_key(name).split() if word in PLACE_KINDS}


def same_name(first: str, second: str) -> bool:
    """
    Les deux noms désignent-ils le même lieu ? Oui s'il reste le même nom une fois retiré le mot qui dit ce qu'est le lieu,
    et si ces mots ne se contredisent pas : « Boulangerie Le Gall » et « Le Gall », « Mercure Bar » et « Café Mercure ».
    Non pour « Marché de Plougonvelin » et « Épicerie de Plougonvelin », ni pour « Café du Port » et « Crêperie du Port ».

    Une seule règle pour toutes les catégories (11 novembre 2026). Avant, chacune avait sa liste de mots : les commerces
    réunissaient un marché et une épicerie du même village, et l'un des deux était perdu (29 commerces sur 136 communes) ;
    « Bar Crêperie La Grotte » ne retrouvait pas « LA GROTTE » au registre.
    """
    kinds, other_kinds = place_kinds(first), place_kinds(second)
    return place_key(first) == place_key(second) and (not kinds or not other_kinds or bool(kinds & other_kinds))


def short_name(name: str) -> str | None:
    """
    Le nom sans le mot du lieu en tête : « Boulangerie Laot » -> « Laot », pour retrouver le service « Laot » d'OSM
    (pilote du 7 novembre 2026 : un nouveau service avait été créé, au 15 au lieu du 16 rue Pen ar Bed). None si le
    nom ne commence pas par un tel mot, ou s'il ne reste qu'un mot trop court pour reconnaître un lieu.
    """
    words = name.split()
    dropped = 0
    while words and (name_key(words[0]) in PLACE_KINDS or name_key(words[0]) in ARTICLES):
        words.pop(0)
        dropped += 1
    rest = " ".join(words)
    return rest if dropped and len(compact_name(rest)) >= 4 else None


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


# LA PAGE D'UN MAGASIN QUE SON ENSEIGNE PROTÈGE (13 novembre 2026, #130)
# carrefour.fr, magasins-u.com et intermarche.com refusent tout programme (réponse 403, protection contre les robots) :
# le code ne peut pas lire la page de leurs magasins, et 15 supermarchés restaient sans preuve. On ne contourne pas
# cette protection. La page est acceptée sans être lue quand son adresse nomme la commune : magasins-u.com/magasin/
# superu-combrit ne peut désigner que le Super U de Combrit, et c'est l'enseigne elle-même qui la publie.
REFUSED_STATUS = 403


def protected_store_page(page: dict, commune: str) -> bool:
    """
    La page du lieu sur son propre site, refusée au code par une protection (403), dont l'adresse nomme la commune.
    Le domaine ne compte pas, seulement le chemin : creperie-plougonvelin.fr ne dit pas de quelle page il s'agit.
    """
    if page.get("type_page") != "site" or page.get("statut") != REFUSED_STATUS or not commune:
        return False
    parts = urlparse(page.get("url") or "")
    return compact_name(commune) in compact_name(f"{parts.path} {parts.query}")


def page_accepted(page: dict, today: date = None, commune: str = "") -> bool:
    """
    Une page acceptée par le code, hors mairie, agrégateur et réseau social. Un article doit en plus être daté et récent.
    La page d'un magasin protégée par son enseigne est acceptée sans être lue (protected_store_page).
    """
    if protected_store_page(page, commune):
        return True
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


# UNE COMMUNE, UNE RECHERCHE (8 novembre 2026). Plusieurs villes de l'appli sont dans la même commune : Crozon, Morgat,
# Le Fret et Tal ar Groas sont toutes en Crozon (29042). Les agents restaurants et commerces cherchent une commune : ils
# la cherchent une fois, depuis la ville qui porte son nom si l'appli l'a (Crozon), sinon depuis la première ville.
def commune_key(city: dict) -> str:
    """Le code INSEE, ou le nom d'une ville dont la commune n'est pas encore connue."""
    return city.get("insee") or city["name"]


def one_city_per_commune(cities: list) -> list:
    """Une ville par commune, dans l'ordre des communes : celle qui porte le nom de la commune, sinon la première."""
    chosen = {}
    for city in cities:
        best = chosen.get(commune_key(city))
        if best is None or (city["name"] == city.get("commune") and best["name"] != best.get("commune")):
            chosen[commune_key(city)] = city
    return list(chosen.values())


def load_cities() -> list:
    """Toutes les villes, avec leur commune officielle (cities.commune et cities.insee, etl/fill_communes.py)."""
    connection = MySQLUtils.connect()
    cursor = connection.cursor()
    cursor.execute("SELECT id, name, commune, insee, latitude, longitude, department FROM cities ORDER BY id")
    rows = _rows(cursor)
    cursor.close()
    MySQLUtils.disconnect(connection)
    return rows


def load_city(name: str) -> dict | None:
    """
    La ville d'où chercher la commune de `name` : Morgat se cherche comme Crozon, depuis la ville Crozon. Trézien, seule
    ville de l'appli en Plouarzel, se cherche comme Plouarzel depuis Trézien. Sans commune connue, la ville elle-même.
    `name` peut aussi être une commune : les traces des agents gardent « Plouarzel », que cities ne nomme pas.
    """
    cities = load_cities()
    asked = (next((city for city in cities if city["name"] == name), None)
             or next((city for city in cities if city.get("commune") == name), None))
    if not asked:
        return None
    return one_city_per_commune([city for city in cities if commune_key(city) == commune_key(asked)])[0]


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


# --- Les lieux déjà en base ---

def _rows(cursor) -> list:
    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def known_services(cursor, city: dict, services: tuple) -> list:
    """
    Les lieux de ces services déjà en base autour de la commune, pour réutiliser leur ligne. Un lieu resté sans position
    (masqué, « position introuvable ») n'est autour de rien : il est rendu avec la commune de la ville où un passage l'a
    créé (le Marché de Morgat, créé depuis Tal ar Groas, se retrouve depuis Crozon). Sans lui, le passage suivant ne le
    retrouvait pas et en aurait créé un second, le premier restant à relire pour toujours (11 novembre 2026 : 79 services
    sans position en attente, aucun n'avait encore été recréé).
    """
    min_lat, min_lon, max_lat, max_lon = get_bounding_box(city["latitude"], city["longitude"], MAX_KM)
    marks = ", ".join(["%s"] * len(services))
    cursor.execute(f"""
        SELECT DISTINCT p.id, p.name, p.address, p.latitude, p.longitude, p.url, p.masque
        FROM poi p JOIN poi_service ps ON ps.poi_id = p.id JOIN services s ON s.id = ps.service_id
        WHERE s.category IN ({marks}) AND (
            (p.latitude BETWEEN %s AND %s AND p.longitude BETWEEN %s AND %s)
            OR (p.latitude IS NULL AND EXISTS (SELECT 1 FROM histo_poi h JOIN cities c ON c.id = h.city_id
                                               WHERE h.poi_id = p.id AND (c.id = %s OR c.insee = %s))))
    """, (*services, min_lat, max_lat, min_lon, max_lon, city["id"], city.get("insee")))
    return _rows(cursor)


def known_sheets(cursor, city: dict, table: str, kinds: tuple = ()) -> list:
    """
    Les lieux visibles qui ont une fiche dans cette table autour de la commune, de ces catégories seulement s'il y en a.
    Un café qui a déjà une fiche restaurant n'est pas enregistré : il s'affiche en restauration (ServiceCategory.
    shown_elsewhere, souhait de l'utilisatrice, 7 novembre 2026). De même une épicerie qui a déjà sa fiche supermarché.
    Seulement si cette fiche est visible : une fiche masquée ne montre rien. Le bar L'Univers (Plougonvelin) n'était
    affiché nulle part, écarté pour une fiche restaurant masquée, à raison : ce n'est pas un restaurant (13 novembre 2026).
    """
    min_lat, min_lon, max_lat, max_lon = get_bounding_box(city["latitude"], city["longitude"], MAX_KM)
    of_kinds = f"AND sheet.categorie IN ({', '.join(['%s'] * len(kinds))})" if kinds else ""
    cursor.execute(f"""
        SELECT p.id, p.name, p.address, p.latitude, p.longitude, p.url, p.masque
        FROM poi p JOIN {table} sheet ON sheet.poi_id = p.id
        WHERE p.masque = 0 AND p.latitude BETWEEN %s AND %s AND p.longitude BETWEEN %s AND %s {of_kinds}
    """, (min_lat, max_lat, min_lon, max_lon, *kinds))
    return _rows(cursor)


def _position(city: dict, address: str | None) -> tuple | None:
    """
    La position de l'adresse, à la rue près, sinon celle de son lieu-dit (une ferme, une crêperie de campagne : la
    moitié des « position introuvable » à relire le 7 novembre 2026). Rien si elle est loin de la commune cherchée.
    """
    if not address:
        return None
    attempts = [(geocode_address_ban, address), (geocode_locality_ban, address)]
    # Deux essais de plus (11 novembre 2026, sur les 79 lieux « position introuvable ») : sans le lieu-dit glissé au
    # milieu de l'adresse, puis en acceptant une rue que la Base Adresse range en lieu-dit.
    if without_locality(address):
        attempts.append((geocode_sure_address_ban, without_locality(address)))
    attempts.append((geocode_way_ban, address))
    for geocode, text in attempts:
        found = geocode(text, city["latitude"], city["longitude"])
        if found and haversine_distance_km(city["latitude"], city["longitude"], *found) <= MAX_KM:
            return found
    return None


def without_locality(address: str) -> str | None:
    """
    L'adresse sans ce qui est glissé entre la rue et la commune : « 10 route de Crozon, Tal ar Groas, 29160 Crozon » ->
    « 10 route de Crozon, 29160 Crozon ». Avec le lieu-dit, la Base Adresse répond « Tal-Ar-Groas » et le numéro est
    perdu ; sans lui, elle trouve le numéro (score 0,96). None si l'adresse n'a pas cette forme.
    """
    parts = [part.strip() for part in address.split(",")]
    if len(parts) < 3 or not re.search(r"\b\d{5}\b", parts[-1]):
        return None
    return f"{parts[0]}, {parts[-1]}"


def _name_rank(name: str, other: str) -> int | None:
    """
    0 : le même nom ; 1 : l'un contient l'autre (« Cinéma Le Dauphin » / « Le Dauphin »), s'ils font au moins 8 lettres ;
    2 : le même nom une fois retiré le mot qui dit ce qu'est le lieu (same_name) : « Riboul Crêperie » et « Riboul » ;
    None sinon. Un nom qui dit ce qu'est un lieu, pas lequel (« Boulangerie »), ne reconnaît personne.

    Le rang 2 est la règle du nom de toute la chaîne (same_name), qui réunit déjà les réponses des recherches et lit le
    registre. Sans lui, « Riboul » (6 lettres, trop court pour le rang 1) n'était pas retrouvé dans « Riboul Crêperie » :
    le pilote du 13 novembre 2026 aurait créé un second Riboul à Plougonvelin.
    """
    key, other_key = name_key(name), name_key(other)
    if is_generic(key) or is_generic(other_key):
        return None
    # Sans les espaces : « Ti Madeo » est « Ti Mad Eo », et « L’Hermine », écrit avec une apostrophe courbe, est « L'Hermine ».
    compact, other_compact = key.replace(" ", ""), other_key.replace(" ", "")
    if compact == other_compact:
        return 0
    if min(len(key), len(other_key)) >= 8 and (compact in other_compact or other_compact in compact):
        return 1
    if len(place_key(name)) >= 4 and same_name(name, other):
        return 2
    return None


def _in_commune(poi: dict, row: dict, city: dict) -> bool:
    """
    Le lieu déjà en base est-il dans la commune du lieu trouvé ? Par le code postal, sinon par la distance au centre.
    Un lieu resté sans position n'est parmi les candidats que par la ville où un passage l'a créé (known_services) : sans
    code postal à comparer, c'est elle qui le dit (La Table de Pierre Bourée, sans adresse, à Gevrey-Chambertin).
    """
    postcodes = [re.search(r"\b\d{5}\b", address or "") for address in (poi.get("address"), row.get("adresse"))]
    if all(postcodes):
        return postcodes[0].group(0) == postcodes[1].group(0)
    if poi["latitude"] is None:
        return True
    return haversine_distance_km(city["latitude"], city["longitude"], poi["latitude"], poi["longitude"]) <= COMMUNE_KM


def find_in(row: dict, position: tuple | None, city: dict, candidates: list, other_names: bool = True,
            within_km: float = SAME_NAME_KM) -> dict | None:
    """
    Le lieu déjà en base, parmi ces candidats : par son nom, puis par son ancien nom (Mary Stuart, devenu La Petite Folie).

    LE NOM NE SUFFIT JAMAIS, IL FAUT AUSSI LE LIEU
    Avant le 11 novembre 2026, le même nom retrouvait un lieu dans un carré de 15 km. Le Galion de Lampaul-Plouarzel a
    ainsi été rattaché à celui de Ploudalmézeau, à 10 km, et la Boulangerie des Abers de Porspoder à celle de Portsall.
    Un nom ne retrouve donc un lieu que :
        - à la même adresse (numéro et rue), où qu'on l'ait placé : Le Commerce de Tréméoc, géocodé à 1,8 km de sa ligne ;
        - ou à moins de within_km de la position trouvée (SAME_NAME_KM, moins pour une enseigne présente à plusieurs
          adresses : ServiceCategory.same_name_km), le plus proche d'abord : l'adresse géocodée et le point d'OSM ne
          tombent pas au même endroit (Cléder : 0,51 km pour le même lieu) ;
        - ou, quand l'adresse n'a pas pu être placée (« Bourg de Lampaul »), s'il est le seul à ce nom dans la commune ;
        - ou, quand c'est le lieu en base qui est resté sans position, à ce nom dans la même commune : l'adresse placée
          aujourd'hui est celle du lieu qui attendait une relecture « position introuvable ».
    L'ancien nom ne vaut qu'avec une position : « Le Triskell », ancien nom du Neuf à Ploudalmézeau, désignait aussi un
    restaurant à 10 km, et Le Neuf a été perdu (7 novembre 2026).
    Sans résultat, le même lieu sous un autre nom est cherché (_same_place).
    Sans other_names, seul le nom exact compte : ni nom contenu dans un autre, ni autre nom au même endroit. C'est le cas
    du nom court, qui a perdu son mot distinctif : « Marché de Carantec », devenu « Carantec », retrouvait « Carantec
    Pizza », et « Crêperie de Saint-Thé » l'Auberge Saint-Thégonnec (mesure du 11 novembre 2026 sur les services en base).
    """
    for name in (row["nom"], row.get("ancien_nom")):
        if not name:
            continue
        named = [(rank, poi) for poi in candidates
                 if (rank := _name_rank(name, poi["name"])) is not None and (other_names or rank == 0)]
        at_address = [(rank, 0, poi) for rank, poi in named if same_address(row.get("adresse"), poi.get("address"))]
        if position:
            near = [(rank, haversine_distance_km(*position, poi["latitude"], poi["longitude"]), poi)
                    for rank, poi in named if poi["latitude"] is not None]
            unplaced = [(rank, 0, poi) for rank, poi in named if poi["latitude"] is None and _in_commune(poi, row, city)]
            found = at_address + [match for match in near if match[1] <= within_km] + unplaced
        elif name == row["nom"]:
            in_commune = [(rank, 0, poi) for rank, poi in named if _in_commune(poi, row, city)]
            found = at_address or (in_commune if len(in_commune) == 1 else [])
        else:
            found = at_address
        if found:
            return min(found, key=lambda match: match[:2])[2]
    return _same_place(row, position, candidates) if other_names else None


def find_known(row: dict, position: tuple | None, city: dict, known: list, within_km: float = SAME_NAME_KM) -> dict | None:
    """
    Le lieu déjà en base, sous son nom puis sous son nom court (« Laot » pour « Boulangerie Laot »), un lieu visible avant
    un lieu masqué : deux jumeaux d'OSM dont la règle des doublons a masqué l'un (poi_duplicates_service.py) feraient sinon
    écarter le lieu. Sans lieu visible, le lieu masqué est rendu : un masquage humain prime.
    """
    short = short_name(row["nom"])
    for candidates in ([poi for poi in known if not poi["masque"]], known):
        poi = find_in(row, position, city, candidates, within_km=within_km)
        if not poi and short:
            # Le nom court doit être le nom même du lieu en base : il a perdu le mot qui distingue un bar d'une crêperie.
            poi = find_in({**row, "nom": short, "ancien_nom": None}, position, city, candidates, other_names=False,
                          within_km=within_km)
        if poi:
            return poi
    return None


def _same_place(row: dict, position: tuple | None, known: list) -> dict | None:
    """
    Le même lieu sous un autre nom : « Racines » et « Restaurant Racines » au même numéro de Crozon,
    « Crêperie La Chaumine » et « La Chaumine Biligou ». Sur 992 pépites, 10 doublons de ce genre (7 novembre 2026).
    Il faut le nom ET le lieu : l'Hostellerie et le Bistrot 1954 partagent une adresse et sont deux tables.
        - même adresse (numéro et rue), et l'un des deux noms contient l'autre ;
        - sans numéro (« Saint-Roch »), le même nom et la même position à SAME_PLACE_KM près.
    Les mots qui disent ce qu'est le lieu ne doivent pas se contredire (same_name) : un bar et une crêperie « du Port »
    restent deux lieux, même à 40 m l'un de l'autre.
    """
    key, kinds = place_key(row["nom"]), place_kinds(row["nom"])
    if len(key) < 4:
        return None
    for poi in known:
        other, other_kinds = place_key(poi["name"]), place_kinds(poi["name"])
        if len(other) < 4 or (kinds and other_kinds and not kinds & other_kinds):
            continue
        if (key in other or other in key) and same_address(row.get("adresse"), poi.get("address")):
            return poi
        if key == other and position and poi["latitude"] is not None \
                and haversine_distance_km(*position, poi["latitude"], poi["longitude"]) <= SAME_PLACE_KM:
            return poi
    return None


# --- Ce qu'un humain a décidé prime ---

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

    def fetchone(self):
        row = self.cursor.fetchone()
        if row is None or isinstance(row, dict):
            return row
        return dict(zip([column[0] for column in self.cursor.description], row))


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


def is_verified(row: dict, accepted: list) -> bool:
    """
    Le badge « Vérifié », le même pour toutes les catégories : une page acceptée par le code nomme le lieu, ou deux sources
    indépendantes le disent, le registre à son nom (registre_depuis) et une page qui cite ce nom, même un annuaire
    (8 novembre 2026, La Meule de Pierre : registre et deux annuaires, sans badge).
    Avant le 11 novembre 2026, la règle était écrite deux fois, et les restaurants n'avaient pas la seconde moitié.
    """
    named = any(page.get("verdict") in AUTO_VERDICTS for page in row.get("pages") or [])
    return bool(accepted) or (bool(row.get("registre_depuis")) and named)


def set_verified(cursor, poi_id: int, verified: bool) -> None:
    """
    Le badge « Vérifié » suit la preuve (7 novembre 2026, is_verified), ou la validation d'un humain. Avant, il disait
    seulement d'où venait la ligne : 1 pour tout POI d'OSM (load_poi.py), 0 pour ceux de l'agent.
    Un lieu gardé par le registre seul reste « Non vérifié » : le registre montre une activité, pas le nom (Leonetti).
    """
    cursor.execute("UPDATE poi SET verifie = %s WHERE id = %s", (int(verified), poi_id))


def validated_by_human(cursor, poi_id: int) -> bool:
    """Un humain a validé ce lieu dans /supervision (valider_pepite) : sa décision prime sur un nouveau passage."""
    cursor.execute("""
        SELECT 1 FROM decisions WHERE objet_type = 'poi' AND objet_id = %s AND annulee_at IS NULL
        AND decision = 'valider_pepite' AND decided_by <> %s LIMIT 1
    """, (poi_id, RULE_AUTHOR))
    return cursor.fetchone() is not None


# --- Les preuves, le lien et les alertes du registre ---

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


def waiting_for_review(cursor, poi_id: int) -> bool:
    """
    La ligne attend une relecture : c'est un agent de la chaîne qui l'a masquée (flag), pas un humain. Peu importe lequel :
    le café masqué par l'agent des commerces est repris par celui des restaurants s'il en trouve la preuve.
    """
    cursor.execute("""SELECT 1 FROM poi_signals WHERE poi_id = %s AND signal_type = 'a_confirmer'
                      AND statut = 'a_relire' LIMIT 1""", (poi_id,))
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
    return any(line.get("nom") and same_name(line["nom"], row["nom"])
               and same_address(row.get("adresse"), line.get("adresse"))
               for line in (register or {}).get("actifs", []))


def clear_contradicted_alerts(category, rows: list, register: dict | None, commune: str) -> None:
    for row in rows:
        if alert_contradicted(row, register):
            category.logger.info(f"[{category.key}] {commune} : alerte de {row['nom']} effacée, le registre a un établissement"
                                 f" actif à ce nom et à cette adresse ({row['alerte_registre']})")
            row["alerte_registre"] = None


def is_liquidated(row: dict) -> bool:
    """Une liquidation judiciaire au registre retire le lieu sans relecture (décision du 5 novembre 2026)."""
    return "liquidation" in name_key(row.get("alerte_registre") or "")


def review_reason(row: dict, located) -> str | None:
    """Pourquoi ce lieu doit attendre une relecture au lieu d'être montré, ou None."""
    if row.get("a_relire"):
        return row["a_relire"]
    if row.get("alerte_registre"):
        return f"registre : {row['alerte_registre']}"
    return None if located else NO_POSITION


# --- L'écriture d'un lieu, de sa fiche et de son signal ---

def create_poi(category, cursor, row: dict, position: tuple | None, city: dict, source_id: int, masked: bool) -> int:
    latitude, longitude = position or (None, None)
    cursor.execute(
        "INSERT INTO poi (name, latitude, longitude, url, address, source_id, verifie, masque)"
        " VALUES (%s, %s, %s, %s, %s, %s, 0, %s)",
        (row["nom"], latitude, longitude, row.get("lien"), row.get("adresse"), source_id, int(masked)))
    poi_id = cursor.lastrowid
    insert_histo_poi(cursor, poi_id, city["name"])
    insert_service_and_link(cursor, poi_id, category.new_service(row))
    return poi_id


def sheet_of(category, row: dict, version: int, model: str) -> dict:
    """Ce qu'il faut pour écrire la fiche plus tard, si un humain valide le lieu à confirmer (poi_review_service.py)."""
    return {**{field: row.get(field) for field in category.sheet_fields}, "prompt_version": version, "model": model}


def save_sheet(category, cursor, poi_id: int, row: dict, version: int, model: str) -> None:
    """La fiche du lieu, dans la table de sa catégorie. Un champ corrigé par un humain garde sa valeur (keep_human_sheet)."""
    row = keep_human_sheet(cursor, category.sheet_table, poi_id, row, category.human_sheet_fields)
    detail, length = category.detail_column
    cursor.execute(f"""
        REPLACE INTO {category.sheet_table} (poi_id, genre, pourquoi, {detail}, ancien_nom, categorie, registre_depuis,
                                             prompt_version, model, trouve_le)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (poi_id, row["genre"][:100], row.get("pourquoi"), (row.get(detail) or "")[:length] or None,
          row.get("ancien_nom"), row.get("categorie"), row.get("registre_depuis"), version, model, datetime.now()))
    # Le lieu a maintenant cette fiche : celle qu'une autre catégorie lui avait donnée et qu'elle remplace s'en va.
    for table, kinds in category.takes_over.items():
        marks = ", ".join(["%s"] * len(kinds))
        cursor.execute(f"DELETE FROM {table} WHERE poi_id = %s AND categorie IN ({marks})", (poi_id, *kinds))


def save_validated_sheet(category, cursor, poi_id: int, sheet: dict) -> None:
    """La fiche d'un lieu à confirmer qu'un humain a validé : celle que l'agent avait préparée."""
    if not sheet or not sheet.get("genre"):
        raise ValueError("Ce lieu n'a pas de fiche préparée par l'agent : il faut le relancer")
    save_sheet(category, cursor, poi_id, sheet, sheet.get("prompt_version"), sheet.get("model"))
    set_verified(cursor, poi_id, True)


def send_to_review(category, cursor, poi_id: int, reason: str, detail: dict) -> bool:
    """
    Le lieu attend une relecture (signal a_confirmer, avec la fiche préparée dans detail). Renvoie True s'il est signalé.
    S'il avait déjà une fiche, elle est retirée : il ne s'affiche plus jusqu'à la décision (7 novembre 2026,
    Leonetti-Degavre restait visible). Valider la réécrit. Un lieu déjà validé par un humain garde sa fiche, et rien
    n'est signalé.
    La même règle pour toutes les catégories (11 novembre 2026) : avant, un restaurant à relire gardait sa fiche et
    restait affiché, sans signal.
    """
    if validated_by_human(cursor, poi_id):
        return False
    cursor.execute(f"DELETE FROM {category.sheet_table} WHERE poi_id = %s", (poi_id,))
    set_verified(cursor, poi_id, False)
    save_signal(cursor, poi_id, category.source, "a_confirmer", {"raison": reason, **detail})
    # Un signal déjà relu revient dans la file : c'est un nouveau doute, d'un nouveau passage.
    cursor.execute("""UPDATE poi_signals SET statut = 'a_relire', reviewed_at = NULL
                      WHERE poi_id = %s AND source = %s AND signal_type = 'a_confirmer'""", (poi_id, category.source))
    return True


def flag(category, cursor, row: dict, position: tuple | None, city: dict, known: list, source_id: int, reason: str, detail: dict,
         link: str | None = None) -> None:
    """
    À confirmer : sur la ligne du lieu s'il est connu, sinon sur une nouvelle ligne masquée, avec la page acceptée
    (link) : confirmer le lieu l'affiche avec son lien (8 novembre 2026, A Fleur d'Eau s'affichait sans son site).
    """
    poi = find_known(row, position, city, known, category.same_name_km)
    if poi and poi["masque"]:
        return
    poi_id = poi["id"] if poi else create_poi(category, cursor, {**row, "lien": link}, position, city, source_id, masked=True)
    send_to_review(category, cursor, poi_id, reason, {"adresse": row.get("adresse"), **detail})


def namesake_in_commune(row: dict, position: tuple | None, city: dict, known: list) -> dict | None:
    """
    Un service visible qui porte ce nom dans la même commune (le même, ou le même sans le mot qui dit ce qu'est le lieu :
    _name_rank 0 ou 2), mais trop loin pour être repris d'office
    (find_in) : le plus proche. Rien pour un nom passe-partout, ni quand l'adresse n'a pas pu être placée.
    """
    if not position:
        return None
    far = [poi for poi in known if not poi["masque"] and poi["latitude"] is not None
           and _name_rank(row["nom"], poi["name"]) in (0, 2) and _in_commune(poi, row, city)]
    return min(far, key=lambda poi: haversine_distance_km(*position, poi["latitude"], poi["longitude"]), default=None)


def flag_namesake(category, cursor, poi_id: int, row: dict, position: tuple, namesake: dict) -> None:
    """
    L'agent vient de créer un service alors qu'un autre porte son nom dans la commune, à plus de same_name_km : le même
    lieu mal placé (Le Castel Ac'h, à 1,7 km de son point d'OSM) ou un second magasin (deux Boulangerie Louise à
    Douarnenez) ? Le code ne tranche pas : un doute dans la file « Doublons », comme ceux de la règle des doublons.
    Le doute est posé sur celui des deux qui n'a pas de fiche, pour que « fusionner » garde celui qui en a une.
    """
    distance_m = round(1000 * haversine_distance_km(*position, namesake["latitude"], namesake["longitude"]))
    reason = "même nom dans la commune, créé par l'agent sans le rattacher"
    cursor.execute(f"SELECT 1 FROM {category.sheet_table} WHERE poi_id = %s", (namesake["id"],))
    if cursor.fetchone():
        doubted, other = poi_id, {"id": namesake["id"], "name": namesake["name"], "address": namesake["address"]}
    else:
        doubted, other = namesake["id"], {"id": poi_id, "name": row["nom"], "address": row.get("adresse")}
    detail = {"autre_id": other["id"], "autre_nom": other["name"], "autre_adresse": other["address"],
              "distance_m": distance_m, "raison": reason}
    save_signal(cursor, doubted, DUPLICATE_SOURCE, DUPLICATE_SIGNAL, {**detail, "autres": [detail]})
    category.logger.info(f"[{category.key}] {row['nom']} : même nom que {namesake['id']} à {distance_m} m dans la commune,"
                         " doute dans la file « Doublons »")


def close_superseded(category, cursor, row: dict, position: tuple | None, city: dict, known: list, poi_id: int) -> bool:
    """
    Le service vient d'être enregistré sur poi_id, visible. Si un autre, masqué, attendait une confirmation pour ce même
    lieu, sa relecture n'a plus d'objet : la règle la classe sans suite, sous son nom, annulable dans /supervision.
    Le 11 novembre 2026, « Hippocampe » (Ouessant) restait à relire sous 32023 alors que le voyageur le voyait sous 850 :
    le confirmer aurait fait un doublon.
    """
    masked = [poi for poi in known if poi["masque"] and poi["id"] != poi_id]
    stale = find_in(row, position, city, masked, within_km=category.same_name_km)
    if not stale or not waiting_for_review(cursor, stale["id"]):
        return False
    from services import poi_review_service        # ici pour éviter une boucle d'imports : il lit ce module au chargement
    poi_review_service.decide_one(_DictRows(cursor), "confirmer", stale["id"], "sans_suite", f"affiché sous le service {poi_id}",
                                  RULE_AUTHOR, None)
    category.logger.info(f"[{category.key}] {row['nom']} : {stale['id']} n'attend plus de relecture, affiché sous {poi_id}")
    return True


def flag_possible_duplicates(category, cursor, rows: list, saved: dict) -> int:
    """
    Les doublons que l'analyste voit et que le code refuse, faute de même adresse : un signal (doublon_commerce) sur le
    lieu, à trancher dans la file « Doublons » de /supervision (fusionner masque celui-ci, l'autre reste).
    """
    flagged = 0
    for row in rows:
        other = row.get("doublon_possible")
        if not other or row["nom"] not in saved or other["nom"] not in saved:
            continue
        here, there = saved[row["nom"]], saved[other["nom"]]
        distance = (round(haversine_distance_km(here["latitude"], here["longitude"], there["latitude"], there["longitude"]) * 1000)
                    if None not in (here["latitude"], there["latitude"]) else None)
        save_signal(cursor, here["id"], category.source, category.duplicate_signal, {
            "raison": f"doublon vu par l'analyste à une autre adresse{' : ' + other['raison'] if other.get('raison') else ''}",
            "autre_id": there["id"], "autre_nom": other["nom"], "autre_adresse": other.get("adresse"), "distance_m": distance})
        flagged += 1
    return flagged


def save_commune(category, city: dict, answer: dict, version: int, model: str, trial: bool = False) -> dict:
    """
    Enregistre une commune en une transaction. Renvoie le nombre de fiches, de lieux à relire et de lieux écartés.
    À l'essai (trial), tout est calculé puis annulé : le bilan dit ce qui serait écrit, la base ne change pas.
    """
    summary = {"fiches": 0, "a_confirmer": 0, "sans_page": 0, "liquidation": 0,
               **{count: 0 for _, _, count, _ in category.shown_elsewhere.values()}}
    sheets, saved = set(), {}
    label = f"[{category.key}] {city['name']}"
    connection = MySQLUtils.connect()
    try:
        cursor = connection.cursor()
        source_id = get_or_create_source(cursor, category.source)
        known = known_services(cursor, city, KNOWN_SERVICES)
        elsewhere = {kind: known_sheets(cursor, city, table, kinds)
                     for kind, (table, kinds, _, _) in category.shown_elsewhere.items()}
        for row in answer[category.key]:
            position = _position(city, row.get("adresse"))
            if row.get("categorie") in elsewhere and find_known(row, position, city, elsewhere[row["categorie"]]):
                _, _, count, why = category.shown_elsewhere[row["categorie"]]
                category.logger.info(f"{label} : {row['nom']} écarté, {why}")
                summary[count] += 1
                continue
            poi = find_known(row, position, city, known, category.same_name_km)
            # Une ligne masquée par un humain ou une décision reste à l'écart ; celle que l'agent a masquée en attendant
            # la relecture se reprend (8 novembre 2026 : A Fleur d'Eau et Episervice restaient bloqués).
            if poi and poi["masque"] and not waiting_for_review(cursor, poi["id"]):
                continue
            if is_liquidated(row):
                category.logger.info(f"{label} : {row['nom']} écarté, {row['alerte_registre']}")
                summary["liquidation"] += 1
                continue
            accepted = [page for page in row["pages"] if category.accepts(page, row, city_commune(city))]
            if not accepted and not row.get("au_registre") and not row.get("a_relire"):
                category.logger.info(f"{label} : {row['nom']} écarté, ni registre ni page acceptée")
                summary["sans_page"] += 1
                continue
            # Placé : par son adresse, ou par la position du lieu déjà en base. Un lieu connu resté sans position ne l'est pas.
            reason = review_reason(row, position or (poi and poi["latitude"] is not None))
            if reason:
                flag(category, cursor, row, position, city, known, source_id, reason,
                     {"indice": row.get("pourquoi"), "page": row.get("lien"),
                      "verdicts": [page.get("verdict") for page in row["pages"]], "fiche": sheet_of(category, row, version, model)},
                     link=best_link(accepted))
                summary["a_confirmer"] += 1
                continue
            # Le lien gardé est toujours une page acceptée, son site si on l'a, et rien sinon.
            row = {**row, "lien": best_link(accepted)}
            if poi:
                # Le lieu existe déjà, peut-être sous le service d'une autre catégorie : il est enrichi, et gagne celui-ci.
                _update_poi(cursor, poi, row, position)
                poi_id = poi["id"]
                insert_service_and_link(cursor, poi_id, category.new_service(row))
            else:
                poi_id = create_poi(category, cursor, row, position, city, source_id, masked=False)
                namesake = namesake_in_commune(row, position, city, known)
                if namesake:
                    flag_namesake(category, cursor, poi_id, row, position, namesake)
                    summary["meme_nom_dans_la_commune"] = summary.get("meme_nom_dans_la_commune", 0) + 1
            _save_season(cursor, poi_id, row)
            save_sheet(category, cursor, poi_id, row, version, model)
            _save_proofs(cursor, poi_id, row["pages"])
            set_verified(cursor, poi_id, is_verified(row, accepted))
            # Le lieu a maintenant sa fiche : il n'attend plus de relecture.
            cursor.execute("DELETE FROM poi_signals WHERE poi_id = %s AND source = %s AND signal_type = 'a_confirmer'",
                           (poi_id, category.source))
            close_superseded(category, cursor, row, position, city, known, poi_id)
            sheets.add(poi_id)
            saved[row["nom"]] = {"id": poi_id, "latitude": (position or (None, None))[0], "longitude": (position or (None, None))[1]}
        summary["fiches"] = len(sheets)
        if category.duplicate_signal:
            summary["doublons_possibles"] = flag_possible_duplicates(category, cursor, answer[category.key], saved)
        if trial:
            connection.rollback()
        else:
            connection.commit()
        cursor.close()
    except Exception:
        connection.rollback()
        raise
    finally:
        MySQLUtils.disconnect(connection)
    category.logger.info(f"{label} : {'essai, rien écrit : ' if trial else ''}{summary}")
    return summary
