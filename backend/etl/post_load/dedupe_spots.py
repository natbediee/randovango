"""
Arbitrage des spots géographiquement quasi confondus.

Le partage des rôles, décidé après lecture des 55 paires détectées par
`etl.clean_spots` :

  Détection - « est-ce le même lieu ? » : c'est de la lecture de texte, donc le
  modèle. Deux parkings distants de 60 m sont souvent deux vrais lieux (un camping
  et le parking d'à côté, deux rues parallèles) ; à l'inverse le seul doublon
  certain de la base est une même rue écrite en français et en breton, que ni la
  distance ni la similarité de chaîne ne rapprochent.

  Départage - « lequel garde-t-on ? » : déterministe, note puis nombre de services
  puis longueur de description. Aucun modèle là-dedans, c'est vérifiable.

  Application - jamais de DELETE. Le perdant pointe vers le gagnant via
  `duplicate_of_spot_id`, ses services sont recopiés sur le gagnant, et les
  requêtes d'affichage filtrent. Réversible d'un UPDATE, source P4N intacte.

Les paires de types différents (un CAMPING contre un PARKING JOUR ET NUIT) sont
écartées sans appel au modèle : 38 des 55 paires disparaissent gratuitement.

Usage (depuis /usr/src/app dans le conteneur backend) :
    python -m etl.enrich.dedupe_spots --dry-run   # arbitre et affiche, n'écrit rien
    python -m etl.enrich.dedupe_spots --apply     # marque les doublons confirmés
"""
import argparse
import json

from etl.clean_spots import DUPLICATE_RADIUS_M, report_geographic_duplicates
from services.llm_service import LLMService, LLMUnavailable
from utils.db_utils import MySQLUtils
from utils.logger_util import LoggerUtil

logger = LoggerUtil.get_logger("etl_dedupe_spots")

DUPLICATE_COLUMN = ("duplicate_of_spot_id", "INT NULL")

VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "same_place": {"type": "boolean"},
        "confidence": {"type": "string", "enum": ["faible", "moyenne", "elevee"]},
        "reason": {"type": "string", "description": "Une phrase, en français."},
    },
    "required": ["same_place", "confidence", "reason"],
    "additionalProperties": False,
}

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
    services = ", ".join(spot.get("services") or []) or "aucun"
    return (
        f"  Nom Park4Night : {spot['name']}\n"
        f"  Type : {spot['type']}\n"
        f"  Note : {spot['rating'] if spot['rating'] is not None else 'aucune'}\n"
        f"  Services : {services}\n"
        f"  Description : {spot['description'] or '(vide)'}"
    )


def build_user_prompt(first: dict, second: dict, distance_m: float) -> str:
    return (
        f"Les deux fiches sont distantes de {distance_m:.0f} mètres.\n\n"
        f"Fiche A (#{first['id']}) :\n{_describe(first)}\n\n"
        f"Fiche B (#{second['id']}) :\n{_describe(second)}"
    )


def rank_key(spot: dict) -> tuple:
    """
    Clé de départage : note, puis nombre de services, puis longueur de description.

    Une note absente compte comme 0 : une fiche notée est mieux étayée qu'une fiche
    sans avis. Le plus grand tuple gagne.
    """
    return (
        spot["rating"] if spot["rating"] is not None else 0.0,
        len(spot.get("services") or []),
        len(spot.get("description") or ""),
    )


def add_missing_column(cursor, database: str) -> None:
    """Ajoute `duplicate_of_spot_id` si le schéma est antérieur (idempotent)."""
    column, sql_type = DUPLICATE_COLUMN
    cursor.execute(
        "SELECT column_name FROM information_schema.columns"
        " WHERE table_schema = %s AND table_name = 'spots' AND column_name = %s",
        (database, column),
    )
    if cursor.fetchone():
        return
    cursor.execute(f"ALTER TABLE spots ADD COLUMN {column} {sql_type}")
    cursor.execute(
        f"ALTER TABLE spots ADD CONSTRAINT fk_spots_duplicate"
        f" FOREIGN KEY ({column}) REFERENCES spots(id)"
    )
    logger.info(f"[dedupe] Colonne spots.{column} ajoutée ({sql_type})")


def load_spot_details(cursor, spot_ids: set) -> dict:
    """Détail des spots concernés par au moins une paire, services compris."""
    if not spot_ids:
        return {}
    placeholders = ",".join(["%s"] * len(spot_ids))
    cursor.execute(
        f"SELECT id, name, description, type, rating FROM spots WHERE id IN ({placeholders})",
        tuple(spot_ids),
    )
    columns = [c[0] for c in cursor.description]
    spots = {row[0]: dict(zip(columns, row)) for row in cursor.fetchall()}

    cursor.execute(
        f"SELECT ss.spot_id, sv.name FROM spot_service ss"
        f" JOIN services sv ON sv.id = ss.service_id"
        f" WHERE ss.spot_id IN ({placeholders})",
        tuple(spot_ids),
    )
    for spot_id, service_name in cursor.fetchall():
        spots[spot_id].setdefault("services", []).append(service_name)
    return spots


def candidate_pairs(cursor) -> list:
    """
    Paires soumises au modèle : proches ET de même type.

    Le filtre sur le type est déterministe et gratuit ; il élimine la majorité des
    paires détectées, qui opposent un camping et le parking voisin.
    """
    pairs = report_geographic_duplicates(cursor)
    spot_ids = {spot_id for pair in pairs for spot_id in (pair[1], pair[4])}
    details = load_spot_details(cursor, spot_ids)

    candidates = []
    for distance, first_id, _, first_type, second_id, _, second_type in pairs:
        if first_type != second_type:
            continue
        candidates.append((distance, details[first_id], details[second_id]))
    logger.info(
        f"[dedupe] {len(candidates)}/{len(pairs)} paire(s) de même type soumises à l'arbitrage"
    )
    return candidates


def arbitrate(service: LLMService, candidates: list) -> list:
    """
    [(gagnant, perdant, distance, verdict)] pour les paires jugées identiques.

    Une paire dont l'arbitrage échoue est simplement ignorée : elle repassera au
    prochain lancement, et en attendant les deux spots restent visibles.
    """
    confirmed = []
    for distance, first, second in candidates:
        try:
            verdict = service.complete_json(
                SYSTEM_PROMPT, build_user_prompt(first, second, distance), VERDICT_SCHEMA
            )
        except (LLMUnavailable, json.JSONDecodeError) as exc:
            logger.warning(f"[dedupe] #{first['id']}/#{second['id']} non arbitrée : {exc}")
            continue

        if not verdict["same_place"]:
            logger.info(
                f"[dedupe] #{first['id']}/#{second['id']} : lieux distincts - {verdict['reason']}"
            )
            continue
        if verdict["confidence"] == "faible":
            logger.info(
                f"[dedupe] #{first['id']}/#{second['id']} : doublon peu sûr, non appliqué"
                f" - {verdict['reason']}"
            )
            continue

        winner, loser = sorted((first, second), key=rank_key, reverse=True)
        confirmed.append((winner, loser, distance, verdict))
        logger.info(
            f"[dedupe] #{loser['id']} → #{winner['id']} ({distance:.0f} m,"
            f" {verdict['confidence']}) - {verdict['reason']}"
        )
    return confirmed


def apply_merges(cursor, confirmed: list) -> int:
    """
    Marque chaque perdant et recopie ses services sur le gagnant.

    Aucune suppression : le spot marqué reste en base avec toute sa donnée, et il
    suffit de remettre `duplicate_of_spot_id` à NULL pour annuler la fusion.
    """
    for winner, loser, _, _ in confirmed:
        cursor.execute(
            "INSERT IGNORE INTO spot_service (spot_id, service_id)"
            " SELECT %s, service_id FROM spot_service WHERE spot_id = %s",
            (winner["id"], loser["id"]),
        )
        cursor.execute(
            "UPDATE spots SET duplicate_of_spot_id = %s WHERE id = %s",
            (winner["id"], loser["id"]),
        )
    logger.info(f"[dedupe] {len(confirmed)} doublon(s) marqué(s), aucune suppression")
    return len(confirmed)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Marquer les doublons confirmés")
    parser.add_argument("--dry-run", action="store_true", help="Arbitrer sans rien écrire")
    args = parser.parse_args()
    if not (args.apply or args.dry_run):
        parser.print_help()
        return

    from utils.service_utils import ServiceUtil

    ServiceUtil.load_env()
    cnx = MySQLUtils.connect()
    cursor = cnx.cursor()

    confirmed = arbitrate(LLMService(), candidate_pairs(cursor))

    if args.apply:
        add_missing_column(cursor, ServiceUtil.get_env("DB_NAME"))
        apply_merges(cursor, confirmed)
        cnx.commit()
    else:
        logger.info(f"[dedupe] Simulation : {len(confirmed)} fusion(s) auraient été appliquées")

    cursor.close()
    MySQLUtils.disconnect(cnx)


if __name__ == "__main__":
    main()
