"""
Les doublons de services : un même lieu chargé deux fois, quel que soit son service (toilettes, attraction, café...).
OSM le dessine souvent deux fois (un point pour le commerce et le contour du bâtiment, ou deux points côte à côte), et
un lieu peut venir à la fois d'OSM, de Wikidata et d'un agent. Le chargement ne compare rien : la seule clé unique de
poi est (original_id, source_id), donc chaque objet devient un lieu.

    même lieu : même nom et même service, à DOUBLE_M au plus (SAME_SPOT_M pour un nom passe-partout comme « Toilettes
                publiques » ou « Point d'eau potable » : deux blocs sur une même plage restent deux lieux). L'un est masqué sous
                le nom RULE_AUTHOR, l'autre reste. Annulable dans la supervision ;
    doute     : même nom à plus de DOUBLE_M (jusqu'à PAIR_M), ou à un autre numéro de la rue, ou deux lieux déjà
                tranchés par un humain. Signal doublon_service, à trancher dans la file « Doublons » de /supervision/services ;
    voisins   : tout le reste. Rien n'est écrit.

LEQUEL RESTE : celui qui a une fiche d'agent (restaurants, commerces), sinon celui qu'un humain a déjà tranché, sinon
celui qui a un lien, sinon celui d'OSM, sinon le plus ancien. Dans un groupe de plus de deux, c'est toujours le même
qui reste.

Deux restaurants qui ont chacun une fiche sont laissés à restaurant_duplicates_service.py, qui a sa propre règle.

JAMAIS DE MASQUAGE AUTOMATIQUE D'UNE FICHE D'AGENT : les agents prennent un lieu masqué pour une décision humaine et
ne le reprennent plus. Le jumeau sans fiche est masqué, celui qui a la fiche reste (les agents reprennent cette ligne).
Deux jumeaux qui ont chacun une fiche, ou un jumeau sans fiche déjà tranché par un humain, font un doute
(choix de l'utilisatrice du 7 novembre 2026 : le moins possible de cas à relire).

UNE DÉCISION HUMAINE PRIME : un lieu dont le signal a déjà été tranché n'est plus repris, et une fusion que quelqu'un a
annulée ne sera pas refaite par la règle. Rien n'est effacé.

7 novembre 2026, premier passage (pilote de 100 lieux puis passe complète) : 349 lieux masqués, 51 doutes. Le 8 novembre,
les abris, parkings et poubelles ont été supprimés de la base et ne sont plus importés : il reste 135 lieux masqués
(toilettes posées au même endroit, commerces dessinés deux fois dans OSM, copies OSM des fiches d'agent) et 25 doutes.

UTILISATION (dans le conteneur backend, depuis /usr/src/app) :
    python -m services.poi_duplicates_service --essai              # compte et liste, n'écrit rien
    python -m services.poi_duplicates_service --limite 100         # pilote : 100 lieux au plus
    python -m services.poi_duplicates_service --ville Plougonvelin
    python -m services.poi_duplicates_service
"""
import argparse

from etl.load.load_poi_checks import save_signal
from etl.transform.transform_osm import DEFAULT_NAME_BY_TYPE
from services import poi_review_service as review
from services.pepite_service import is_generic, name_key
from services.restaurant_service import place_key, street_words
from utils.db_utils import MySQLUtils
from utils.geo_utils import haversine_distance_km
from utils.logger_util import LoggerUtil

logger = LoggerUtil.get_logger("poi_duplicates")

SOURCE = "doublons"
SIGNAL = "doublon_service"
TAB = "doublons"
RULE_AUTHOR = review.RULE_AUTHOR
DOUBLE_M = 25
PAIR_M = 50
SAME_SPOT_M = 3
# Environ 0,0005 degré de latitude = 55 m : au-delà, deux lieux triés par latitude ne peuvent plus faire une paire.
LATITUDE_WINDOW = 0.0005
SAME_PLACE, DOUBT = "meme_lieu", "doute"
OSM, WIKIDATA = "osm", "wikidata"
AGENT_SOURCES = ("agent_restaurants", "agent_commerces")
# Les noms qui disent ce qu'est un lieu, pas lequel : ceux que le chargement OSM donne aux lieux sans nom, et quelques
# autres. 5 « Toilettes publiques » à 1 m l'une de l'autre à Quimper sont un seul endroit, pas 5.
PLAIN_NAMES = {name_key(name) for name in (*DEFAULT_NAME_BY_TYPE.values(), "Toilettes", "WC", "Sanitaires", "PMR", "Abri bus")}


def is_plain_name(name: str) -> bool:
    key = name_key(name)
    return not key or key in PLAIN_NAMES or is_generic(key)


def street_number(address: str | None) -> str | None:
    return next((word for word in street_words(address) if word.isdigit()), None)


def same_service(first: dict, second: dict) -> bool:
    """
    Un service en commun, ou un même onglet de l'étape 4. Wikidata et les agents ne rangent pas un lieu comme OSM
    (« fortification » et « museum », « cafe » et « restaurant ») : le même nom au même endroit suffit alors.
    """
    if first["categories"] & second["categories"]:
        return True
    if {first["source"], second["source"]} & {WIKIDATA, *AGENT_SOURCES}:
        return True
    tabs = {review.step4_tab(category) for category in first["categories"]}
    return bool(tabs - {review.NO_TAB} & {review.step4_tab(category) for category in second["categories"]})


def rank(place: dict) -> tuple:
    """Plus grand = celui qui reste."""
    return (place["sheet"], place["decided"], bool(place["url"]), place["source"] == OSM, -place["id"])


def _sheet_doubt(first: dict, second: dict) -> str | None:
    """La raison d'un doute dû aux fiches d'agent, ou None si l'un des deux peut être masqué."""
    if first["sheet"] and second["sheet"]:
        return "même nom, deux fiches d'agent"
    if first["sheet"] != second["sheet"] and (second if first["sheet"] else first)["decided"]:
        return "même nom, le lieu sans fiche a déjà été tranché"
    return None


def verdict(first: dict, second: dict, distance_m: float) -> tuple | None:
    """(verdict, raison) pour deux lieux proches, ou None si ce sont deux voisins."""
    if place_key(first["name"]) != place_key(second["name"]) or not same_service(first, second):
        return None
    if first["sheet"] and second["sheet"] and first["restaurant"] and second["restaurant"]:
        return None
    if is_plain_name(first["name"]):
        if distance_m >= SAME_SPOT_M:
            return None
        reason = _sheet_doubt(first, second)
        return (DOUBT, reason) if reason else (SAME_PLACE, "même nom, au même endroit")
    numbers = street_number(first["address"]), street_number(second["address"])
    if all(numbers) and numbers[0] != numbers[1]:
        return DOUBT, "même nom, autre numéro de la rue"
    if first["decided"] and second["decided"]:
        return DOUBT, "même nom, deux lieux déjà tranchés"
    if distance_m > DOUBLE_M:
        return DOUBT, f"même nom, à plus de {DOUBLE_M} m"
    reason = _sheet_doubt(first, second)
    if reason:
        return DOUBT, reason
    return SAME_PLACE, "même nom, même service"


def find_pairs(places: list) -> list:
    """(distance en m, celui qui reste, l'autre, verdict, raison) pour chaque paire qui n'est pas de simples voisins."""
    places = sorted(places, key=lambda place: place["latitude"])
    pairs = []
    for index, first in enumerate(places):
        for second in places[index + 1:]:
            if second["latitude"] - first["latitude"] > LATITUDE_WINDOW:
                break
            distance_m = 1000 * haversine_distance_km(first["latitude"], first["longitude"],
                                                      second["latitude"], second["longitude"])
            if distance_m > PAIR_M:
                continue
            found = verdict(first, second, distance_m)
            if found:
                kept, other = sorted((first, second), key=rank, reverse=True)
                pairs.append((round(distance_m), kept, other, *found))
    return pairs


def plan(pairs: list) -> list:
    """
    (verdict, lieu concerné, détails) pour chaque lieu à masquer ou à relire. Les meilleurs lieux passent d'abord : un
    lieu masqué ne fait masquer personne, sinon une chaîne de lieux à 20 m l'un de l'autre disparaîtrait en entier.
    """
    masked, actions, doubts = set(), {}, {}
    for distance, kept, other, found, reason in sorted(pairs, key=lambda pair: rank(pair[1]), reverse=True):
        detail = {"autre_id": kept["id"], "autre_nom": kept["name"], "autre_adresse": kept["address"],
                  "distance_m": distance, "raison": reason}
        if found == SAME_PLACE and kept["id"] not in masked and other["id"] not in masked:
            masked.add(other["id"])
            actions[other["id"]] = (SAME_PLACE, other, [detail])
        elif found == DOUBT:
            doubts.setdefault(other["id"], (other, []))[1].append(detail)
    for poi_id, (place, details) in doubts.items():
        if poi_id in actions:
            actions[poi_id][2].extend(details)
        else:
            actions[poi_id] = (DOUBT, place, details)
    return [actions[poi_id] for poi_id in sorted(actions)]


def _visible_places(cursor) -> list:
    cursor.execute("""
        SELECT p.id, p.name, p.address, p.url, p.latitude, p.longitude, s.name AS source,
               (SELECT GROUP_CONCAT(sv.category) FROM poi_service ps JOIN services sv ON sv.id = ps.service_id
                WHERE ps.poi_id = p.id) AS categories,
               EXISTS (SELECT 1 FROM restaurants r WHERE r.poi_id = p.id) AS restaurant,
               EXISTS (SELECT 1 FROM commerces c WHERE c.poi_id = p.id) AS commerce,
               EXISTS (SELECT 1 FROM decisions d WHERE d.objet_type = %s AND d.objet_id = p.id
                       AND d.annulee_at IS NULL AND d.decided_by <> %s) AS decided
        FROM poi p LEFT JOIN sources s ON s.id = p.source_id
        WHERE p.masque = 0 AND p.latitude IS NOT NULL AND p.longitude IS NOT NULL
    """, (review.POI, RULE_AUTHOR))
    return [{**row, "latitude": float(row["latitude"]), "longitude": float(row["longitude"]), "address": row["address"] or "",
             "categories": set((row["categories"] or "").lower().split(",")) - {""},
             "restaurant": bool(row["restaurant"]), "sheet": bool(row["restaurant"] or row["commerce"]),
             "decided": bool(row["decided"])}
            for row in cursor.fetchall()]


def _city_ids(cursor, city: str) -> set:
    cursor.execute("SELECT h.poi_id FROM histo_poi h JOIN cities c ON c.id = h.city_id WHERE c.name = %s", (city,))
    return {row["poi_id"] for row in cursor.fetchall()}


def _already_handled(cursor, poi_id: int) -> bool:
    """Le signal a été tranché, ou quelqu'un a annulé la fusion faite par la règle : on n'y revient pas."""
    cursor.execute("SELECT 1 FROM poi_signals WHERE poi_id = %s AND signal_type = %s AND statut <> 'a_relire'", (poi_id, SIGNAL))
    if cursor.fetchone():
        return True
    cursor.execute("""
        SELECT 1 FROM decisions WHERE objet_type = %s AND objet_id = %s AND decision = 'fusionner'
        AND decided_by = %s AND annulee_at IS NOT NULL
    """, (review.POI, poi_id, RULE_AUTHOR))
    return cursor.fetchone() is not None


def run(trial: bool, city: str | None = None, limit: int | None = None) -> dict:
    """Masque chaque doublon sûr et signale chaque doute, sur le lieu qui ne reste pas. Une transaction."""
    summary = {"paires": 0, SAME_PLACE: 0, DOUBT: 0, "deja_tranches": 0}
    connection = MySQLUtils.connect()
    try:
        cursor = connection.cursor(dictionary=True)
        pairs = find_pairs(_visible_places(cursor))
        if city:
            in_city = _city_ids(cursor, city)
            pairs = [pair for pair in pairs if pair[1]["id"] in in_city or pair[2]["id"] in in_city]
        summary["paires"] = len(pairs)
        for found, place, details in plan(pairs):
            if limit is not None and summary[SAME_PLACE] + summary[DOUBT] >= limit:
                break
            if _already_handled(cursor, place["id"]):
                summary["deja_tranches"] += 1
                continue
            summary[found] += 1
            first = details[0]
            logger.info(f"[doublons] {found} : {place['id']} {place['name']} ({place['address']}) / {first['autre_id']} "
                        f"{first['autre_nom']}, {first['distance_m']} m, {first['raison']}")
            if trial:
                continue
            save_signal(cursor, place["id"], SOURCE, SIGNAL, {**first, "autres": details})
            if found == SAME_PLACE:
                review.decide_one(cursor, TAB, place["id"], "fusionner", "", RULE_AUTHOR, None)
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
    logger.info(f"[doublons] {'essai, rien écrit : ' if trial else ''}{city or 'toutes les villes'} {summary}")
    return summary


def after_load(city: str) -> None:
    """
    Après le chargement OSM ou Wikidata d'une ville : ses nouveaux doublons sont traités tout de suite. Une erreur ici
    ne doit pas faire échouer le chargement, déjà fait.
    """
    try:
        run(False, city)
    except Exception as error:
        logger.error(f"[doublons] {city} : règle des doublons en échec, à relancer à la main ({error})")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--essai", action="store_true", help="Compte et liste, n'écrit rien en base")
    parser.add_argument("--ville", help="Seulement les paires dont un lieu est rattaché à cette ville")
    parser.add_argument("--limite", type=int, help="Nombre de lieux traités au plus (pilote)")
    args = parser.parse_args()
    print(run(args.essai, args.ville, args.limite))


if __name__ == "__main__":
    main()
