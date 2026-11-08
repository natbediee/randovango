"""
Enregistre ce que l'agent find_commerces.py a trouvé, avec les mêmes règles que les restaurants (restaurant_service.py).

    fiche    : le registre ou une page acceptée montre le commerce, et on a une position. Le lieu s'affiche à l'étape 4 ;
    à relire : un tel lieu, mais sans position, avec une alerte du registre, ou que l'agent n'a pas pu trancher
               (row["a_relire"]), en signal a_confirmer, masqué s'il est nouveau. Le signal garde la fiche préparée :
               la valider dans /supervision l'enregistre (save_validated_sheet). Une fiche déjà en base est retirée
               jusqu'à la décision, sauf si un humain avait validé le lieu (send_to_review) ;
    écarté   : ni registre ni page acceptée, ou une liquidation judiciaire. Rien n'est écrit en base.

CE QUI CHANGE POUR LES COMMERCES
- Un marché n'a pas de société au registre, et sa meilleure page est souvent celle de la mairie, qui l'organise.
  La page de la mairie, refusée pour un restaurant (elle garde des lieux fermés), est donc acceptée pour un marché.
- La fiche garde « jours » (le jour et l'heure d'un marché) à la place de la distinction.
- Un commerce créé par l'agent prend le service OSM de sa catégorie (commerce_selection_service.SHOP_SERVICES).
- Un café qui a déjà une fiche restaurant n'est pas enregistré : il s'affiche en restauration (souhait de l'utilisatrice,
  7 novembre 2026, sans rien changer à la recherche des restaurants).
- Un lieu se retrouve aussi par son nom court : « Boulangerie Laot » est « Laot » d'OSM.

Le reste vient tel quel de restaurant_service.py : retrouver la ligne d'un lieu connu, garder les décisions humaines,
la saison, les preuves. Un lieu déjà masqué est ignoré : une décision humaine prime.
"""
from datetime import datetime

from agents.find_service_links import AUTO_VERDICTS, TYPE_RANK
from etl.load.load_poi import get_or_create_source, insert_histo_poi, insert_service_and_link
from etl.load.load_poi_checks import save_signal
from services import restaurant_service
from services.commerce_selection_service import CAFE, CAFE_SERVICES, COMMERCE_SERVICES, MARKET, SHOP_SERVICES
from services.pepite_service import name_key
from services.restaurant_service import (_find_known, best_link, waiting_for_review, _position, _rows, _save_proofs, _save_season, _update_poi,
                                         is_liquidated, keep_human_sheet, review_reason, set_verified)
from utils.db_utils import MySQLUtils
from utils.geo_utils import get_bounding_box, haversine_distance_km
from utils.logger_util import LoggerUtil

logger = LoggerUtil.get_logger("agent_commerces")

SOURCE = "agent_commerces"
DUPLICATE_SIGNAL = "doublon_commerce"
# Les services OSM de l'onglet « commerce » : on y cherche la ligne d'un commerce déjà connu. Pas les supermarchés.
KNOWN_SERVICES = COMMERCE_SERVICES + CAFE_SERVICES
SHOP_WORDS = ("boulangerie", "patisserie", "epicerie", "superette", "marche", "ferme", "fromagerie", "boucherie",
              "poissonnerie", "cave", "cafe", "bar")
SHEET_FIELDS = ("genre", "pourquoi", "jours", "ancien_nom", "categorie", "registre_depuis")


def place_key(name: str) -> str:
    """« Boulangerie Le Gall » et « Le Gall », « Marché de Plougonvelin » et « Plougonvelin » sont le même lieu."""
    words = [word for word in name_key(name).split() if word not in SHOP_WORDS]
    while words and words[0] in ("l", "la", "le", "les", "d", "de", "du", "des"):
        words.pop(0)
    return "".join(words) or restaurant_service.compact_name(name)


def short_name(name: str) -> str | None:
    """
    Le nom sans le mot du commerce en tête : « Boulangerie Laot » -> « Laot », pour retrouver la ligne « Laot » d'OSM
    (pilote du 7 novembre 2026 : une nouvelle ligne avait été créée, au 15 au lieu du 16 rue Pen ar Bed). None si le
    nom ne commence pas par un tel mot, ou s'il ne reste qu'un mot trop court pour reconnaître un lieu.
    """
    words = name.split()
    dropped = 0
    while words and name_key(words[0]) in SHOP_WORDS + ("l", "la", "le", "les", "d", "de", "du", "des"):
        words.pop(0)
        dropped += 1
    rest = " ".join(words)
    return rest if dropped and len(restaurant_service.compact_name(rest)) >= 4 else None


def find_known(row: dict, position: tuple | None, city: dict, known: list) -> dict | None:
    """
    La ligne du lieu sous son nom, sinon sous son nom court (« Laot » pour « Boulangerie Laot »). Une ligne visible passe
    avant une ligne masquée : deux jumeaux d'OSM dont la règle des doublons a masqué l'un (poi_duplicates_service.py)
    feraient sinon écarter le commerce. Sans ligne visible, la ligne masquée est rendue : un masquage humain prime.
    """
    visible = [poi for poi in known if not poi["masque"]]
    for candidates in (visible, known):
        poi = _find_known(row, position, city, candidates)
        short = short_name(row["nom"])
        if not poi and short:
            poi = _find_known({**row, "nom": short, "ancien_nom": None}, position, city, candidates)
        if poi:
            return poi
    return None


def page_accepted(page: dict, categorie: str | None, commune: str = "") -> bool:
    """La règle des restaurants, sauf pour un marché : la page de sa mairie le prouve (elle l'organise)."""
    if categorie == MARKET and (page.get("type_page") == "mairie"
                                or (commune and restaurant_service.is_town_hall(page.get("url") or "", commune))):
        return restaurant_service.page_accepted({**page, "type_page": "site"})
    return restaurant_service.page_accepted(page, commune=commune)


def registered_and_named(row: dict) -> bool:
    """
    Deux sources indépendantes : le registre au nom du lieu (registre_depuis) et une page qui cite ce nom, même un
    agrégateur. Le badge « Vérifié » suit (8 novembre 2026, La Meule de Pierre : registre et deux annuaires, sans badge).
    """
    return bool(row.get("registre_depuis")) and any(page.get("verdict") in AUTO_VERDICTS for page in row.get("pages") or [])


def _known_commerces(cursor, city: dict) -> list:
    """Les commerces déjà en base autour de la commune, pour réutiliser leur ligne."""
    min_lat, min_lon, max_lat, max_lon = get_bounding_box(city["latitude"], city["longitude"], restaurant_service.MAX_KM)
    marks = ", ".join(["%s"] * len(KNOWN_SERVICES))
    cursor.execute(f"""
        SELECT DISTINCT p.id, p.name, p.address, p.latitude, p.longitude, p.url, p.masque
        FROM poi p JOIN poi_service ps ON ps.poi_id = p.id JOIN services s ON s.id = ps.service_id
        WHERE s.category IN ({marks}) AND p.latitude BETWEEN %s AND %s AND p.longitude BETWEEN %s AND %s
    """, (*KNOWN_SERVICES, min_lat, max_lat, min_lon, max_lon))
    return _rows(cursor)


def _known_tables(cursor, city: dict) -> list:
    """
    Les lieux qui ont une fiche de l'agent restaurants autour de la commune. Un café qui en est un n'est pas enregistré :
    il s'affiche déjà en restauration. La recherche des restaurants n'est pas touchée, le contrôle se fait ici.
    """
    min_lat, min_lon, max_lat, max_lon = get_bounding_box(city["latitude"], city["longitude"], restaurant_service.MAX_KM)
    cursor.execute("""
        SELECT p.id, p.name, p.address, p.latitude, p.longitude, p.url, p.masque
        FROM poi p JOIN restaurants r ON r.poi_id = p.id
        WHERE p.latitude BETWEEN %s AND %s AND p.longitude BETWEEN %s AND %s
    """, (min_lat, max_lat, min_lon, max_lon))
    return _rows(cursor)


def _create_poi(cursor, row: dict, position: tuple | None, city: dict, source_id: int, masked: bool) -> int:
    latitude, longitude = position or (None, None)
    cursor.execute(
        "INSERT INTO poi (name, latitude, longitude, url, address, source_id, verifie, masque)"
        " VALUES (%s, %s, %s, %s, %s, %s, 0, %s)",
        (row["nom"], latitude, longitude, row.get("lien"), row.get("adresse"), source_id, int(masked)))
    poi_id = cursor.lastrowid
    insert_histo_poi(cursor, poi_id, city["name"])
    insert_service_and_link(cursor, poi_id, SHOP_SERVICES.get(row.get("categorie"), "shop"))
    return poi_id


def sheet_of(row: dict, version: int, model: str) -> dict:
    """Ce qu'il faut pour écrire la fiche plus tard, si un humain valide le lieu à confirmer (poi_review_service.py)."""
    return {**{field: row.get(field) for field in SHEET_FIELDS}, "prompt_version": version, "model": model}


def _save_sheet(cursor, poi_id: int, row: dict, version: int, model: str) -> None:
    # Les champs corrigés par un humain dans la supervision gardent sa valeur (restaurant_service.keep_human_sheet).
    row = keep_human_sheet(cursor, "commerces", poi_id, row, ("genre", "pourquoi", "jours", "categorie"))
    cursor.execute("""
        REPLACE INTO commerces (poi_id, genre, pourquoi, jours, ancien_nom, categorie, registre_depuis,
                                prompt_version, model, trouve_le)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (poi_id, row["genre"][:100], row.get("pourquoi"), (row.get("jours") or "")[:150] or None,
          row.get("ancien_nom"), row.get("categorie"), row.get("registre_depuis"), version, model, datetime.now()))


def save_validated_sheet(cursor, poi_id: int, sheet: dict) -> None:
    """La fiche d'un commerce à confirmer qu'un humain a validé : celle que l'agent avait préparée."""
    if not sheet or not sheet.get("genre"):
        raise ValueError("Ce lieu n'a pas de fiche préparée par l'agent : il faut le relancer")
    _save_sheet(cursor, poi_id, sheet, sheet.get("prompt_version"), sheet.get("model"))
    set_verified(cursor, poi_id, True)


def validated_by_human(cursor, poi_id: int) -> bool:
    """Un humain a validé ce lieu dans /supervision (valider_pepite) : sa décision prime sur un nouveau passage."""
    cursor.execute("""
        SELECT 1 FROM decisions WHERE objet_type = 'poi' AND objet_id = %s AND annulee_at IS NULL
        AND decision = 'valider_pepite' AND decided_by <> %s LIMIT 1
    """, (poi_id, restaurant_service.RULE_AUTHOR))
    return cursor.fetchone() is not None


def send_to_review(cursor, poi_id: int, reason: str, detail: dict) -> bool:
    """
    Le lieu attend une relecture (signal a_confirmer, avec la fiche préparée dans detail). S'il avait déjà une fiche, elle
    est retirée : il ne s'affiche plus jusqu'à la décision (7 novembre 2026, Leonetti-Degavre restait visible). Valider
    la réécrit. Un lieu déjà validé par un humain garde sa fiche, et rien n'est signalé. Renvoie True si le lieu est signalé.
    """
    if validated_by_human(cursor, poi_id):
        return False
    cursor.execute("DELETE FROM commerces WHERE poi_id = %s", (poi_id,))
    set_verified(cursor, poi_id, False)
    save_signal(cursor, poi_id, SOURCE, "a_confirmer", {"raison": reason, **detail})
    # Un signal déjà relu revient dans la file : c'est un nouveau doute, d'un nouveau passage.
    cursor.execute("""UPDATE poi_signals SET statut = 'a_relire', reviewed_at = NULL
                      WHERE poi_id = %s AND source = %s AND signal_type = 'a_confirmer'""", (poi_id, SOURCE))
    return True


def _flag(cursor, row: dict, position: tuple | None, city: dict, known: list, source_id: int, reason: str, detail: dict,
          link: str | None = None) -> None:
    """
    À confirmer : sur la ligne du lieu s'il est connu, sinon sur une nouvelle ligne masquée, avec la page acceptée
    (link) : confirmer le lieu l'affiche avec son lien (restaurant_service._flag).
    """
    poi = find_known(row, position, city, known)
    if poi and poi["masque"]:
        return
    poi_id = poi["id"] if poi else _create_poi(cursor, {**row, "lien": link}, position, city, source_id, masked=True)
    send_to_review(cursor, poi_id, reason, {"adresse": row.get("adresse"), **detail})


def _flag_possible_duplicates(cursor, rows: list, saved: dict) -> int:
    """
    Les doublons que l'analyste voit et que le code refuse, faute de même adresse : un signal doublon_commerce sur le
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
        save_signal(cursor, here["id"], SOURCE, DUPLICATE_SIGNAL, {
            "raison": f"doublon vu par l'analyste à une autre adresse{' : ' + other['raison'] if other.get('raison') else ''}",
            "autre_id": there["id"], "autre_nom": other["nom"], "autre_adresse": other.get("adresse"), "distance_m": distance})
        flagged += 1
    return flagged


def save_commune(city: dict, answer: dict, version: int, model: str) -> dict:
    """Enregistre une commune en une transaction. Renvoie le nombre de fiches, de lieux à relire et de lieux écartés."""
    summary = {"fiches": 0, "a_confirmer": 0, "sans_page": 0, "liquidation": 0, "deja_restaurant": 0}
    sheets = set()
    connection = MySQLUtils.connect()
    try:
        cursor = connection.cursor()
        source_id = get_or_create_source(cursor, SOURCE)
        known = _known_commerces(cursor, city)
        tables = _known_tables(cursor, city)
        saved = {}
        for row in answer["commerces"]:
            position = _position(city, row.get("adresse"))
            if row.get("categorie") == CAFE and _find_known(row, position, city, tables):
                logger.info(f"[commerces] {city['name']} : {row['nom']} écarté, déjà une fiche restaurant")
                summary["deja_restaurant"] += 1
                continue
            poi = find_known(row, position, city, known)
            # Une ligne masquée par un humain ou une décision reste à l'écart ; celle que l'agent a masquée en attendant
            # la relecture se reprend (8 novembre 2026 : A Fleur d'Eau et Episervice restaient bloqués).
            if poi and poi["masque"] and not waiting_for_review(cursor, poi["id"], SOURCE):
                continue
            if is_liquidated(row):
                logger.info(f"[commerces] {city['name']} : {row['nom']} écarté, {row['alerte_registre']}")
                summary["liquidation"] += 1
                continue
            accepted = [page for page in row["pages"] if page_accepted(page, row.get("categorie"), city["name"])]
            if not accepted and not row.get("au_registre") and not row.get("a_relire"):
                logger.info(f"[commerces] {city['name']} : {row['nom']} écarté, ni registre ni page acceptée")
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
            # Le lien gardé est toujours une page acceptée, son site si on l'a, et rien sinon.
            row = {**row, "lien": best_link(accepted)}
            if poi:
                _update_poi(cursor, poi, row, position)
                poi_id = poi["id"]
            else:
                poi_id = _create_poi(cursor, row, position, city, source_id, masked=False)
            _save_season(cursor, poi_id, row)
            _save_sheet(cursor, poi_id, row, version, model)
            _save_proofs(cursor, poi_id, row["pages"])
            # « Vérifié » si une page acceptée nomme le lieu (restaurant_service.set_verified), ou deux sources le disent.
            set_verified(cursor, poi_id, bool(accepted) or registered_and_named(row))
            # Le lieu a maintenant sa fiche : il n'attend plus de relecture.
            cursor.execute("DELETE FROM poi_signals WHERE poi_id = %s AND source = %s AND signal_type = 'a_confirmer'",
                           (poi_id, SOURCE))
            sheets.add(poi_id)
            saved[row["nom"]] = {"id": poi_id, "latitude": (position or (None, None))[0], "longitude": (position or (None, None))[1]}
        summary["fiches"] = len(sheets)
        summary["doublons_possibles"] = _flag_possible_duplicates(cursor, answer["commerces"], saved)
        connection.commit()
        cursor.close()
    except Exception:
        connection.rollback()
        raise
    finally:
        MySQLUtils.disconnect(connection)
    logger.info(f"[commerces] {city['name']} : {summary}")
    return summary
