"""
Repérage des spots en double (le même lieu saisi deux fois sur Park4Night).

C'est une transformation POST-CHARGEMENT (voir agents/__init__.py) :
elle a besoin de voir TOUS les spots déjà en base pour trouver les paires.

LE PROBLÈME
On cherche d'abord les paires de spots très proches (moins de DUPLICATE_RADIUS_M
mètres). Mais être proches ne veut pas dire être en double :
  - deux parkings à 60 m l'un de l'autre sont souvent deux vrais lieux
    (un camping et le parking d'à côté, deux rues parallèles...) ;
  - à l'inverse, un vrai doublon peut être difficile à repérer, par exemple la
    même rue écrite en français sur une fiche et en breton sur l'autre.
Seule la lecture des descriptions permet de trancher.

LA MÉTHODE, EN 4 ÉTAPES
  1. Filtrer (gratuit) : on écarte les paires de types différents (un CAMPING
     et un PARKING ne sont pas le même lieu). Cela élimine environ 38 paires sur 55.
  2. Demander à Claude : pour chaque paire restante, « est-ce le même lieu ? ».
  3. Choisir le spot à garder : sans IA, avec une règle simple et vérifiable
     (la meilleure note, puis le plus de services, puis la plus longue description).
  4. Marquer le doublon : on ne SUPPRIME JAMAIS rien. Le spot écarté reçoit
     dans `duplicate_of_spot_id` l'id du spot gardé, et le site ne l'affiche plus.
     Pour annuler, il suffit de remettre cette colonne à NULL.

UTILISATION (dans le conteneur backend, depuis /usr/src/app)
    python -m agents.dedupe_spots --dry-run   # affiche les décisions, n'écrit rien
    python -m agents.dedupe_spots --apply     # enregistre les doublons en base
    (ajouter --engine claude-code pour utiliser l'abonnement Claude au lieu de la clé d'API)
"""
import argparse
import json

from agents.harmonize_spots import update_spot_service_table
from agents.llm_config import ENGINE_API, ENGINE_CLAUDE_CODE, make_llm_service
from agents.llm_service import LLMUnavailable
from utils.db_utils import MySQLUtils
from utils.geo_utils import haversine_distance_km
from utils.logger_util import LoggerUtil
from utils.service_utils import ServiceUtil

logger = LoggerUtil.get_logger("etl_dedupe_spots")


# =============================================================================
# 1. CE QU'ON DEMANDE À CLAUDE
# =============================================================================

# Deux spots plus proches que ce seuil forment une paire candidate au doublon.
DUPLICATE_RADIUS_M = 80

# Colonne ajoutée à `spots` : l'id du spot gardé, ou NULL si le spot n'est pas un doublon.
DUPLICATE_COLUMN = ("duplicate_of_spot_id", "INT NULL")

# Forme de la réponse attendue de Claude (son "verdict") pour une paire.
VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "same_place": {"type": "boolean"},  # True = même lieu, donc doublon
        "confidence": {"type": "string", "enum": ["faible", "moyenne", "elevee"]},
        "reason": {"type": "string", "description": "Une phrase, en français."},
    },
    "required": ["same_place", "confidence", "reason"],
    "additionalProperties": False,
}

# Les consignes données à Claude. Le "f" devant les guillemets permet d'insérer
# la valeur de DUPLICATE_RADIUS_M dans le texte.
SYSTEM_PROMPT = f"""Tu compares deux fiches Park4Night distantes de moins de {DUPLICATE_RADIUS_M} mètres et de
même type, pour dire s'il s'agit du MÊME lieu saisi deux fois, ou de deux lieux voisins distincts.

À cette distance, deux lieux distincts sont le cas le plus fréquent : deux rues qui se croisent,
deux parkings mitoyens aux règles différentes, deux services d'un même centre commercial. Ne
conclus au doublon que si les descriptions parlent visiblement du même emplacement.

Indices de doublon : mêmes caractéristiques décrites (même vue, même équipement, même contrainte),
ou même voie désignée de deux façons - orthographe variable, numéro absent d'un côté, nom français
et nom breton de la même rue.

Indices de lieux distincts : contraintes contradictoires (l'un payant, l'autre gratuit ; l'un
limité en hauteur, l'autre non), tailles ou revêtements différents, voies clairement différentes,
services de nature différente.

Dans le doute, réponds `same_place` faux : fusionner deux vrais lieux fait perdre de l'information,
ne pas fusionner un doublon n'en fait perdre aucune.

Réponds en français."""


def _describe(spot: dict) -> str:
    """Présente une fiche en quelques lignes lisibles, pour le message envoyé à Claude."""
    services = ", ".join(spot.get("services") or []) or "aucun"

    if spot["rating"] is not None:
        rating = spot["rating"]
    else:
        rating = "aucune"

    return (
        f"  Nom Park4Night : {spot['name']}\n"
        f"  Type : {spot['type']}\n"
        f"  Note : {rating}\n"
        f"  Services : {services}\n"
        f"  Description : {spot['description'] or '(vide)'}"
    )


def build_user_prompt(first: dict, second: dict, distance_m: float) -> str:
    """Écrit le message envoyé à Claude pour une paire : la distance et les deux fiches."""
    return (
        # {distance_m:.0f} affiche la distance arrondie, sans décimale (66.4 -> "66").
        f"Les deux fiches sont distantes de {distance_m:.0f} mètres.\n\n"
        f"Fiche A (#{first['id']}) :\n{_describe(first)}\n\n"
        f"Fiche B (#{second['id']}) :\n{_describe(second)}"
    )


# =============================================================================
# 2. CHOISIR LE SPOT À GARDER (sans IA)
# =============================================================================

def rank_key(spot: dict) -> tuple:
    """
    Donne un "score" à un spot pour décider lequel garder dans une paire.

    Le score est un tuple (note, nombre de services, longueur de la description).
    Python compare les tuples élément par élément : d'abord la note ; en cas
    d'égalité, le nombre de services ; puis la longueur de la description.
    Le spot qui a le plus grand tuple est gardé.

    Un spot sans note compte comme 0 : un spot noté est mieux renseigné.
    """
    if spot["rating"] is not None:
        rating = spot["rating"]
    else:
        rating = 0.0

    number_of_services = len(spot.get("services") or [])
    description_length = len(spot.get("description") or "")

    return (rating, number_of_services, description_length)


# =============================================================================
# 3. LIRE LA BASE MYSQL
# =============================================================================

def find_close_pairs(cursor) -> list:
    """
    Liste les paires de spots distants de moins de DUPLICATE_RADIUS_M.
    Chaque paire est un tuple (distance, id A, nom A, type A, id B, nom B, type B),
    de la plus proche à la plus éloignée.

    Pour ne pas comparer chaque spot à tous les autres (1 700 x 1 700), on trie
    les spots par latitude : dès que l'écart de latitude dépasse ~111 m, les
    spots suivants sont forcément trop loin, et on passe au spot suivant.
    """
    cursor.execute(
        "SELECT id, name, type, latitude, longitude FROM spots"
        " WHERE id > 0 AND latitude IS NOT NULL AND longitude IS NOT NULL"
        " ORDER BY latitude"
    )
    spots = cursor.fetchall()
    lat_window = 0.001  # ~0.001° de latitude ≈ 111 m

    pairs = []
    for i, (spot_id, name, spot_type, lat, lon) in enumerate(spots):
        for other_id, other_name, other_type, other_lat, other_lon in spots[i + 1:]:
            if other_lat - lat > lat_window:
                break
            distance = haversine_distance_km(lat, lon, other_lat, other_lon) * 1000  # en mètres
            if distance < DUPLICATE_RADIUS_M:
                pairs.append((distance, spot_id, name, spot_type, other_id, other_name, other_type))

    pairs.sort()
    logger.info(f"[dedupe] {len(pairs)} paire(s) de spots à moins de {DUPLICATE_RADIUS_M} m")
    return pairs


def load_spot_details(cursor, spot_ids: set) -> dict:
    """
    Charge le détail des spots demandés, avec leurs services.
    Renvoie un dict {id du spot: infos du spot}.
    """
    if not spot_ids:
        return {}

    # On fabrique "%s,%s,%s" (un %s par id) pour la clause IN (...) du SQL.
    placeholders = ",".join(["%s"] * len(spot_ids))
    ids = tuple(spot_ids)

    # 1. Les infos des spots.
    cursor.execute(
        f"SELECT id, name, description, type, rating FROM spots WHERE id IN ({placeholders})",
        ids,
    )
    column_names = [column[0] for column in cursor.description]
    spots = {}
    for row in cursor.fetchall():
        spot = dict(zip(column_names, row))  # tuple -> dict {"id": ..., "name": ...}
        spots[spot["id"]] = spot

    # 2. Leurs services (rangés dans une autre table).
    cursor.execute(
        f"SELECT spot_service.spot_id, services.name"
        f" FROM spot_service"
        f" JOIN services ON services.id = spot_service.service_id"
        f" WHERE spot_service.spot_id IN ({placeholders})",
        ids,
    )
    for spot_id, service_name in cursor.fetchall():
        spots[spot_id].setdefault("services", []).append(service_name)

    return spots


def candidate_pairs(cursor) -> list:
    """
    Renvoie les paires à soumettre à Claude : proches ET de même type.
    Chaque paire est un tuple (distance, spot A, spot B).
    """
    # Les paires de spots proches. Chaque paire est :
    # (distance, id A, nom A, type A, id B, nom B, type B)
    pairs = find_close_pairs(cursor)

    # On charge en une seule fois le détail de tous les spots concernés.
    spot_ids = set()
    for pair in pairs:
        spot_ids.add(pair[1])  # id A
        spot_ids.add(pair[4])  # id B
    details = load_spot_details(cursor, spot_ids)

    candidates = []
    for distance, first_id, _, first_type, second_id, _, second_type in pairs:
        # Types différents (ex : CAMPING / PARKING) : ce n'est pas le même lieu,
        # inutile de demander à Claude.
        if first_type != second_type:
            continue
        candidates.append((distance, details[first_id], details[second_id]))

    logger.info(f"[dedupe] {len(candidates)}/{len(pairs)} paire(s) de même type soumises à Claude")
    return candidates


# =============================================================================
# 4. DEMANDER À CLAUDE ET DÉCIDER
# =============================================================================

def arbitrate(service, candidates: list) -> list:
    """
    Demande à Claude, pour chaque paire, s'il s'agit du même lieu.

    Renvoie la liste des doublons confirmés, sous la forme
    (spot gardé, spot écarté, distance, verdict de Claude).

    Une paire n'est retenue que si Claude répond "même lieu" avec une confiance
    moyenne ou élevée. Si l'appel à Claude échoue, la paire est simplement
    ignorée : les deux spots restent visibles et la paire sera retentée au
    prochain lancement.

    Chaque décision est écrite dans les logs sur une ligne qui se suffit à
    elle-même (les deux fiches, la distance, la décision et sa raison), pour
    pouvoir relire les décisions avant de lancer --apply.
    """
    confirmed = []

    for distance, first, second in candidates:
        # Ex : #931 "(29160) Crozon - 30 Avenue du Revestel" / #929 "..." (58 m, CAMPING)
        pair_label = (
            f'#{first["id"]} "{first["name"]}" / #{second["id"]} "{second["name"]}"'
            f" ({distance:.0f} m, {first['type']})"
        )

        try:
            verdict = service.complete_json(
                SYSTEM_PROMPT, build_user_prompt(first, second, distance), VERDICT_SCHEMA
            )
        except (LLMUnavailable, json.JSONDecodeError) as error:
            logger.warning(f"[dedupe] {pair_label} -> NON ARBITRÉE : {error}")
            continue

        if not verdict["same_place"]:
            logger.info(f"[dedupe] {pair_label} -> lieux distincts : {verdict['reason']}")
            continue

        if verdict["confidence"] == "faible":
            # Dans le doute, on ne fusionne pas.
            logger.info(f"[dedupe] {pair_label} -> doublon peu sûr, non fusionné : {verdict['reason']}")
            continue

        # On trie les deux spots du meilleur au moins bon (reverse=True) selon rank_key.
        winner, loser = sorted((first, second), key=rank_key, reverse=True)
        confirmed.append((winner, loser, distance, verdict))
        logger.info(
            f"[dedupe] {pair_label} -> DOUBLON ({verdict['confidence']}), on garde #{winner['id']}"
            f" et on écarte #{loser['id']} : {verdict['reason']}"
        )

    return confirmed


# =============================================================================
# 5. ÉCRIRE DANS LA BASE MYSQL
# =============================================================================

def add_missing_column(cursor, database: str) -> None:
    """
    Ajoute la colonne `duplicate_of_spot_id` à `spots` si elle n'existe pas encore.
    On peut l'appeler plusieurs fois sans risque.
    """
    column, sql_type = DUPLICATE_COLUMN

    cursor.execute(
        "SELECT column_name FROM information_schema.columns"
        " WHERE table_schema = %s AND table_name = 'spots' AND column_name = %s",
        (database, column),
    )
    if cursor.fetchone():
        return  # la colonne existe déjà

    cursor.execute(f"ALTER TABLE spots ADD COLUMN {column} {sql_type}")
    # Clé étrangère : MySQL vérifiera que l'id indiqué correspond bien à un spot existant.
    cursor.execute(
        f"ALTER TABLE spots ADD CONSTRAINT fk_spots_duplicate"
        f" FOREIGN KEY ({column}) REFERENCES spots(id)"
    )
    logger.info(f"[dedupe] Colonne spots.{column} ajoutée ({sql_type})")


def apply_merges(cursor, confirmed: list) -> int:
    """
    Enregistre les doublons confirmés en base. Renvoie leur nombre.

    Pour chaque paire :
      1. les services du spot écarté sont recopiés sur le spot gardé ;
      2. le spot écarté est marqué comme doublon du spot gardé.
    Rien n'est supprimé : pour annuler, on remet `duplicate_of_spot_id` à NULL.
    """
    for winner, loser, _distance, _verdict in confirmed:
        # 1. Recopier les services, avec leur source ('p4n' ou 'ia'). "INSERT
        #    IGNORE" ignore les services que le spot gardé possède déjà, au lieu
        #    de provoquer une erreur.
        cursor.execute(
            "INSERT IGNORE INTO spot_service (spot_id, service_id, source)"
            " SELECT %s, service_id, source FROM spot_service WHERE spot_id = %s",
            (winner["id"], loser["id"]),
        )
        # 2. Marquer le doublon.
        cursor.execute(
            "UPDATE spots SET duplicate_of_spot_id = %s WHERE id = %s",
            (winner["id"], loser["id"]),
        )

    logger.info(f"[dedupe] {len(confirmed)} doublon(s) marqué(s), aucune suppression")
    return len(confirmed)


# =============================================================================
# 6. LANCEMENT EN LIGNE DE COMMANDE
# =============================================================================

def main():
    # argparse lit les options tapées après le nom du script.
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Enregistrer les doublons en base")
    parser.add_argument("--dry-run", action="store_true", help="Afficher les décisions sans rien écrire")
    parser.add_argument(
        "--engine", choices=[ENGINE_API, ENGINE_CLAUDE_CODE],
        help="api : clé ANTHROPIC_API_KEY ; claude-code : programme `claude` + abonnement",
    )
    args = parser.parse_args()

    if not (args.apply or args.dry_run):
        parser.print_help()
        return

    ServiceUtil.load_env()
    connection = MySQLUtils.connect()
    cursor = connection.cursor()

    # Choix de la façon d'appeler Claude (même option que harmonize_spots).
    service = make_llm_service("dedupe_spots", chosen_engine=args.engine)

    confirmed = arbitrate(service, candidate_pairs(cursor))

    if args.apply:
        add_missing_column(cursor, ServiceUtil.get_env("DB_NAME"))
        # La recopie des services a besoin de la colonne spot_service.source.
        update_spot_service_table(cursor, ServiceUtil.get_env("DB_NAME"))
        apply_merges(cursor, confirmed)
        connection.commit()
    else:
        logger.info(f"[dedupe] Simulation : {len(confirmed)} fusion(s) auraient été appliquées")

    cursor.close()
    MySQLUtils.disconnect(connection)


if __name__ == "__main__":
    main()
