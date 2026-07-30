"""
4e étape de l'ETL : extract -> transform -> load -> enrich.

Le seul travail qui résiste au SQL : produire un champ éditorial homogène à
partir de descriptions contributeurs hétérogènes (récits à la première personne,
brochures de camping, notes de trois mots). Le modèle ne réécrit pas la donnée
source, il en extrait une couche d'affichage à côté.

Deux garde-fous non négociables :
  - `description` n'est JAMAIS écrasée. L'enrichissement va dans des colonnes
    dédiées, donc la source Park4Night reste intacte et re-jouable.
  - Pas d'invention. Un spot dont la description tient en deux mots doit
    ressortir pauvre, avec une confiance basse - pas enjolivé. C'est dit
    explicitement dans le prompt et vérifié par le seuil de publication.

Idempotence : `source_hash` est l'empreinte du texte source. Tant qu'il n'a pas
bougé, le spot n'est pas ré-enrichi, même si le script est relancé.

Usage (depuis /usr/src/app dans le conteneur backend) :
    python -m etl.enrich.enrich_spots --sample 20     # échantillon, appels unitaires
    python -m etl.enrich.enrich_spots --submit        # backfill : soumet le lot
    python -m etl.enrich.enrich_spots --collect <id>  # backfill : écrit les résultats
"""
import argparse
import hashlib
import json

from services.llm_service import LLMService, LLMUnavailable
from utils.db_utils import MySQLUtils
from utils.logger_util import LoggerUtil
from utils.service_utils import SERVICE_CATEGORY_MAP

logger = LoggerUtil.get_logger("etl_enrich_spots")

# Colonnes ajoutées par l'enrichissement. Toutes annulables : un spot non enrichi
# reste parfaitement affichable, le front retombe sur les champs d'origine.
ENRICHMENT_COLUMNS = {
    "display_name": "VARCHAR(255)",
    "description_ia": "TEXT",
    "tags": "JSON",
    "noise_level": "VARCHAR(20)",
    "access_difficulty": "VARCHAR(20)",
    "services_inferred": "JSON",
    "stale_info": "TINYINT(1)",
    "confidence": "VARCHAR(10)",
    "enriched_at": "DATETIME",
    "source_hash": "CHAR(64)",
}

# Vocabulaire fermé : le modèle choisit dans cette liste, il n'invente pas de tag.
TAGS = [
    "calme", "bruyant", "vue_mer", "vue_montagne", "ombrage", "plein_soleil",
    "bord_de_route", "isole", "centre_ville", "payant", "gratuit",
    "interdiction_signalee", "acces_etroit", "sol_meuble", "frequente",
]

# Idem pour les services : la liste est celle de la table `services` côté P4N,
# pour que `services_inferred` soit directement rapprochable de `spot_service`.
SERVICE_NAMES = sorted(SERVICE_CATEGORY_MAP.keys())

SPOT_SCHEMA = {
    "type": "object",
    "properties": {
        "display_name": {
            "type": "string",
            "description": "Nom de lieu lisible, ou chaîne vide si le texte source n'en donne aucun.",
        },
        "summary": {
            "type": "string",
            "description": "Résumé neutre, 3e personne, présent, 200 caractères maximum.",
        },
        "tags": {"type": "array", "items": {"type": "string", "enum": TAGS}},
        "noise_level": {"type": "string", "enum": ["calme", "modere", "bruyant", "inconnu"]},
        "access_difficulty": {"type": "string", "enum": ["facile", "moyen", "difficile", "inconnu"]},
        "services_inferred": {"type": "array", "items": {"type": "string", "enum": SERVICE_NAMES}},
        "stale_info": {"type": "boolean"},
        "confidence": {"type": "string", "enum": ["faible", "moyenne", "elevee"]},
    },
    "required": [
        "display_name", "summary", "tags", "noise_level",
        "access_difficulty", "services_inferred", "stale_info", "confidence",
    ],
    "additionalProperties": False,
}

SYSTEM_PROMPT = f"""Tu structures des fiches de stationnement pour camping-cars et vans, à partir de
contributions d'utilisateurs de Park4Night. Ces textes sont bruts : récits personnels, notes
télégraphiques, copies marketing de campings. Tu en extraits une couche d'affichage homogène.

Règle absolue : n'invente rien. Tu ne disposes que du texte fourni. Si une information n'y est pas,
elle n'existe pas pour toi :
- aucun nom de lieu identifiable -> `display_name` vaut la chaîne vide
- texte trop pauvre pour résumer -> `summary` reprend le peu qui est dit, sans étoffer
- niveau sonore ou difficulté d'accès non évoqués -> "inconnu"
- ne déduis jamais un service d'un type de lieu ("camping" n'implique pas des douches)

`display_name` : un nom de lieu, pas une adresse. "Parking du jardin botanique", "Aire de la
plage du Vougot". Le code postal, le numéro de rue et le nom de commune fournis en contexte
servent à te situer, ils ne doivent pas apparaître dans le nom.

`summary` : 200 caractères maximum, une à deux phrases. Troisième personne, présent, ton neutre.
Le récit devient un fait : "Nous avons dormi une nuit, très calme" -> "Stationnement calme,
adapté à une nuit." Pas de tarif chiffré, pas de date, pas de "je"/"nous".

`services_inferred` : uniquement les services explicitement décrits dans le texte, choisis dans la
liste imposée. Liste vide si le texte n'en mentionne aucun.

`stale_info` : vrai si le texte contient une information périssable - date, année, tarif, mention
de travaux, "en ce moment", "actuellement", équipement signalé hors service.

`confidence` : "elevee" si le texte est descriptif et factuel ; "moyenne" s'il est court ou
partiellement anecdotique ; "faible" s'il fait moins d'une phrase utile ou ne décrit pas le lieu.

Réponds en français."""


def source_hash(spot: dict) -> str:
    """
    Empreinte de ce que le modèle a réellement lu.

    Inclut les services : ils font partie du contexte envoyé, donc un service
    ajouté côté P4N doit déclencher un ré-enrichissement au même titre qu'une
    description modifiée.
    """
    payload = "␟".join([
        spot.get("name") or "",
        spot.get("description") or "",
        spot.get("type") or "",
        ",".join(sorted(spot.get("services") or [])),
    ])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_user_prompt(spot: dict) -> str:
    """Contexte d'un spot, en clair. Le champ `description` est le seul texte libre."""
    services = ", ".join(spot.get("services") or []) or "aucun"
    return (
        f"Commune : {spot.get('city_label') or 'inconnue'}\n"
        f"Code postal : {spot.get('postal_code') or 'inconnu'}\n"
        f"Repère fourni par Park4Night : {spot.get('place_label') or 'aucun'}\n"
        f"Type de lieu : {spot.get('type') or 'inconnu'}\n"
        f"Services déjà connus : {services}\n"
        f"Description contributeur :\n{spot.get('description') or '(vide)'}"
    )


def add_missing_columns(cursor, database: str) -> None:
    """Ajoute les colonnes d'enrichissement absentes du schéma (idempotent)."""
    cursor.execute(
        "SELECT column_name FROM information_schema.columns"
        " WHERE table_schema = %s AND table_name = 'spots'",
        (database,),
    )
    existing = {row[0] for row in cursor.fetchall()}
    for column, sql_type in ENRICHMENT_COLUMNS.items():
        if column in existing:
            continue
        cursor.execute(f"ALTER TABLE spots ADD COLUMN {column} {sql_type}")
        logger.info(f"[enrich] Colonne spots.{column} ajoutée ({sql_type})")


def fetch_spots_to_enrich(cursor, limit: int = None) -> list:
    """
    Spots dont le texte source a changé (ou qui n'ont jamais été enrichis).

    Le hash est recalculé en Python plutôt que comparé en SQL : il porte sur les
    services, qui vivent dans une table liée.
    """
    query = """
        SELECT s.id, s.name, s.description, s.type, s.postal_code, s.city_label,
               s.place_label, s.source_hash
        FROM spots s
        WHERE s.id > 0
        ORDER BY s.id
    """
    cursor.execute(query)
    spots = [dict(zip([c[0] for c in cursor.description], row)) for row in cursor.fetchall()]

    cursor.execute(
        "SELECT ss.spot_id, sv.name FROM spot_service ss JOIN services sv ON sv.id = ss.service_id"
    )
    services = {}
    for spot_id, service_name in cursor.fetchall():
        services.setdefault(spot_id, []).append(service_name)

    pending = []
    for spot in spots:
        spot["services"] = services.get(spot["id"], [])
        spot["computed_hash"] = source_hash(spot)
        if spot["computed_hash"] != spot["source_hash"]:
            pending.append(spot)

    logger.info(f"[enrich] {len(pending)}/{len(spots)} spot(s) à (ré)enrichir")
    return pending[:limit] if limit else pending


def normalize(payload: dict) -> dict:
    """
    Ramène la sortie du modèle à ce qui va réellement en base.

    Le schéma JSON garantit les types et les valeurs autorisées, mais pas les
    contraintes de longueur (non supportées par l'API) : le résumé est donc tronqué
    ici, et un `display_name` vide devient NULL plutôt qu'une chaîne vide, pour que
    le front puisse retomber franchement sur le nom d'origine.
    """
    summary = (payload.get("summary") or "").strip()
    if len(summary) > 200:
        summary = summary[:199].rsplit(" ", 1)[0] + "…"
    display_name = (payload.get("display_name") or "").strip()
    return {
        "display_name": display_name or None,
        "description_ia": summary or None,
        "tags": json.dumps(payload.get("tags") or [], ensure_ascii=False),
        "noise_level": payload.get("noise_level") or "inconnu",
        "access_difficulty": payload.get("access_difficulty") or "inconnu",
        "services_inferred": json.dumps(payload.get("services_inferred") or [], ensure_ascii=False),
        "stale_info": 1 if payload.get("stale_info") else 0,
        "confidence": payload.get("confidence") or "faible",
    }


def write_enrichment(cursor, spot_id: int, computed_hash: str, payload: dict) -> None:
    """Écrit l'enrichissement d'un spot. `description` n'est pas dans la requête."""
    fields = normalize(payload)
    cursor.execute(
        """
        UPDATE spots SET display_name = %s, description_ia = %s, tags = %s,
                         noise_level = %s, access_difficulty = %s, services_inferred = %s,
                         stale_info = %s, confidence = %s,
                         enriched_at = NOW(), source_hash = %s
        WHERE id = %s
        """,
        (
            fields["display_name"], fields["description_ia"], fields["tags"],
            fields["noise_level"], fields["access_difficulty"], fields["services_inferred"],
            fields["stale_info"], fields["confidence"], computed_hash, spot_id,
        ),
    )


def enrich_one(service: LLMService, spot: dict) -> dict:
    """Enrichit un spot par un appel unitaire (spots fraîchement scrapés, échantillon)."""
    return service.complete_json(SYSTEM_PROMPT, build_user_prompt(spot), SPOT_SCHEMA)


def run_sample(sample: int) -> None:
    """Enrichit un échantillon en direct, pour juger la qualité avant le backfill complet."""
    service = LLMService()
    cnx = MySQLUtils.connect()
    cursor = cnx.cursor()
    add_missing_columns(cursor, _database())
    cnx.commit()

    spots = fetch_spots_to_enrich(cursor, limit=sample)
    for spot in spots:
        try:
            payload = enrich_one(service, spot)
        except (LLMUnavailable, json.JSONDecodeError) as exc:
            logger.warning(f"[enrich] Spot {spot['id']} ignoré : {exc}")
            continue
        write_enrichment(cursor, spot["id"], spot["computed_hash"], payload)
        logger.info(
            f"[enrich] #{spot['id']} {payload.get('display_name') or '(sans nom)'}"
            f" [{payload.get('confidence')}] {payload.get('summary')}"
        )
    cnx.commit()
    cursor.close()
    MySQLUtils.disconnect(cnx)


def submit_backfill() -> str:
    """Soumet tous les spots à ré-enrichir en un lot. Retourne l'identifiant du lot."""
    service = LLMService()
    cnx = MySQLUtils.connect()
    cursor = cnx.cursor()
    add_missing_columns(cursor, _database())
    cnx.commit()

    spots = fetch_spots_to_enrich(cursor)
    cursor.close()
    MySQLUtils.disconnect(cnx)
    if not spots:
        logger.info("[enrich] Rien à enrichir")
        return ""

    requests = [
        service.build_batch_request(
            custom_id=f"spot-{spot['id']}",
            system=SYSTEM_PROMPT,
            user=build_user_prompt(spot),
            schema=SPOT_SCHEMA,
        )
        for spot in spots
    ]
    batch_id = service.submit_batch(requests)
    logger.info(f"[enrich] Lot {batch_id} : relire avec --collect {batch_id}")
    return batch_id


def collect_backfill(batch_id: str) -> int:
    """Écrit en base les résultats d'un lot terminé. Retourne le nombre de spots enrichis."""
    service = LLMService()
    if not service.batch_finished(batch_id):
        logger.info(f"[enrich] Lot {batch_id} encore en cours")
        return 0

    payloads = service.fetch_batch_results(batch_id)
    cnx = MySQLUtils.connect()
    cursor = cnx.cursor()
    # Les hash sont recalculés au moment de l'écriture : si P4N a modifié un texte
    # entre la soumission et la relecture, le spot repassera au prochain backfill.
    by_id = {spot["id"]: spot for spot in fetch_spots_to_enrich(cursor)}

    written = 0
    for custom_id, payload in payloads.items():
        spot = by_id.get(int(custom_id.removeprefix("spot-")))
        if not spot:
            continue
        write_enrichment(cursor, spot["id"], spot["computed_hash"], payload)
        written += 1

    cnx.commit()
    cursor.close()
    MySQLUtils.disconnect(cnx)
    logger.info(f"[enrich] {written} spot(s) enrichi(s) depuis le lot {batch_id}")
    return written


def _database() -> str:
    from utils.service_utils import ServiceUtil

    ServiceUtil.load_env()
    return ServiceUtil.get_env("DB_NAME")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=int, help="Enrichir N spots en appels unitaires")
    parser.add_argument("--submit", action="store_true", help="Soumettre le backfill complet")
    parser.add_argument("--collect", metavar="BATCH_ID", help="Écrire les résultats d'un lot")
    args = parser.parse_args()

    if args.sample:
        run_sample(args.sample)
    elif args.submit:
        submit_backfill()
    elif args.collect:
        collect_backfill(args.collect)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
