"""
Le rattrapage des doublons de restaurants déjà en base : la règle que service_store.py applique à l'enregistrement
(find_in), rejouée sur les pépites visibles. Elle teste la règle sur les vraies données, comme le fera le code.

    même lieu : la règle le reconnaît (même adresse et un nom qui contient l'autre, ou même nom à 50 m sans numéro).
                Le plus récent est masqué sous le nom RULE_AUTHOR, l'autre reste. Annulable dans la supervision ;
    doute     : même adresse sans nom proche, ou nom proche à une autre adresse. Signal doublon_restaurant, à trancher
                dans la file « Doublons » de /supervision/services ;
    voisins   : deux tables proches, ni même adresse ni nom proche. Rien n'est écrit.

D'OÙ VIENNENT LES PAIRES
Deux pépites visibles à moins de PAIR_KM l'une de l'autre : 357 paires le 7 novembre 2026, dont 10 doublons sûrs
(Racines et Restaurant Racines à Crozon...). Une même adresse partagée par plusieurs tables reste un doute, jamais une
fusion : l'Hostellerie et le Bistrot 1954 du Conquet en sont deux.

UNE DÉCISION HUMAINE PRIME : un lieu dont le signal a déjà été tranché n'est plus repris. Rien n'est effacé.

UTILISATION (dans le conteneur backend, depuis /usr/src/app) :
    python -m services.restaurant_duplicates_service --essai   # compte et liste, n'écrit rien
    python -m services.restaurant_duplicates_service
"""
import argparse

from etl.load.load_poi_checks import save_signal
from services.supervision import services_review as review
from services import service_store
from services.service_store import place_key, same_address
from utils.db_utils import MySQLUtils
from utils.geo_utils import haversine_distance_km
from utils.logger_util import LoggerUtil

logger = LoggerUtil.get_logger("agent_restaurants")

SOURCE = "doublons"
SIGNAL = "doublon_restaurant"
TAB = "doublons"
RULE_AUTHOR = "règle automatique"
PAIR_KM = 0.05
SAME_PLACE, DOUBT = "meme_lieu", "doute"


def verdict(first: dict, second: dict) -> tuple | None:
    """(verdict, raison) pour deux pépites proches, ou None si ce sont deux voisins."""
    position = (second["latitude"], second["longitude"])
    city = {"latitude": second["latitude"], "longitude": second["longitude"]}
    if service_store.find_in({"nom": second["name"], "adresse": second["address"]}, position, city, [first]):
        return SAME_PLACE, "même lieu selon la règle"
    if same_address(first["address"], second["address"]):
        return DOUBT, "même adresse, autre nom"
    keys = place_key(first["name"]), place_key(second["name"])
    if min(len(key) for key in keys) >= 4 and (keys[0] in keys[1] or keys[1] in keys[0]):
        return DOUBT, "nom proche, autre adresse"
    return None


def find_pairs(places: list) -> list:
    """(distance en m, le plus ancien, le plus récent, verdict, raison) pour chaque paire qui n'est pas de simples voisins."""
    places = sorted(places, key=lambda place: place["latitude"])
    pairs = []
    for index, first in enumerate(places):
        for second in places[index + 1:]:
            if second["latitude"] - first["latitude"] > 0.001:
                break
            distance = haversine_distance_km(first["latitude"], first["longitude"], second["latitude"], second["longitude"])
            if distance > PAIR_KM:
                continue
            older, newer = sorted((first, second), key=lambda place: place["id"])
            found = verdict(older, newer) or verdict(newer, older)
            if found:
                pairs.append((round(distance * 1000), older, newer, *found))
    return pairs


def _visible_places(cursor) -> list:
    cursor.execute("""
        SELECT p.id, p.name, p.address, p.latitude, p.longitude FROM poi p JOIN restaurants r ON r.poi_id = p.id
        WHERE p.masque = 0 AND p.latitude IS NOT NULL
    """)
    return [{**row, "latitude": float(row["latitude"]), "longitude": float(row["longitude"])} for row in cursor.fetchall()]


def _already_decided(cursor, poi_id: int) -> bool:
    cursor.execute("SELECT 1 FROM poi_signals WHERE poi_id = %s AND signal_type = %s AND statut <> 'a_relire'", (poi_id, SIGNAL))
    return cursor.fetchone() is not None


def run(trial: bool) -> dict:
    """Signale chaque doublon sur le lieu le plus récent, et fusionne ceux que la règle reconnaît. Une transaction."""
    summary = {"paires": 0, SAME_PLACE: 0, DOUBT: 0, "deja_tranches": 0}
    connection = MySQLUtils.connect()
    try:
        cursor = connection.cursor(dictionary=True)
        by_place = {}
        for distance, older, newer, found, reason in find_pairs(_visible_places(cursor)):
            summary["paires"] += 1
            by_place.setdefault(newer["id"], []).append((found, {"autre_id": older["id"], "autre_nom": older["name"],
                                                                 "autre_adresse": older["address"], "distance_m": distance,
                                                                 "raison": reason}))
            logger.info(f"[doublons] {found} : {newer['name']} ({newer['address']}) / {older['name']}, {distance} m, {reason}")
        for poi_id, found in by_place.items():
            if _already_decided(cursor, poi_id):
                summary["deja_tranches"] += 1
                continue
            same = [other for kind, other in found if kind == SAME_PLACE]
            # Le même lieu d'abord : c'est lui que la carte de relecture montre.
            others = same + [other for kind, other in found if kind != SAME_PLACE]
            summary[SAME_PLACE if same else DOUBT] += 1
            if trial:
                continue
            save_signal(cursor, poi_id, SOURCE, SIGNAL, {**others[0], "autres": others})
            if same:
                review.decide_one(cursor, TAB, poi_id, "fusionner", "", RULE_AUTHOR, None)
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
    logger.info(f"[doublons] {'essai, rien écrit : ' if trial else ''}{summary}")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--essai", action="store_true", help="Compte et liste, n'écrit rien en base")
    args = parser.parse_args()
    print(run(args.essai))


if __name__ == "__main__":
    main()
