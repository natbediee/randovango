"""
Vérification sur le web des informations temporaires des spots.

C'est une transformation POST-CHARGEMENT (voir agents/__init__.py), qui
vient APRÈS l'harmonisation : celle-ci marque `a_verifier = 1` les spots dont la
fiche signale une situation temporaire décisive (fermeture, travaux, interdiction
récente, équipement en panne). Cet agent cherche sur le web si elle est toujours
d'actualité.

CE N'EST PAS DE L'HARMONISATION, C'EST DE L'ENRICHISSEMENT
Le web est une source externe à Park4Night. Le résultat est donc rangé à part,
dans la table `spot_verifications` (statut, résumé, sources, date), et la fiche
du spot n'est jamais modifiée. On garde l'historique : une ligne par vérification.

ON NE REFAIT PAS LE TRAVAIL DEUX FOIS
Un spot est à vérifier s'il est marqué `a_verifier` et n'a pas été vérifié depuis
sa dernière harmonisation.

UTILISATION (dans le conteneur backend, depuis /usr/src/app)
    python -m agents.verify_spots --sample 10
    python -m agents.verify_spots --all
    python -m agents.verify_spots --id 37 85

La recherche web passe par le programme `claude` (abonnement) : il n'y a pas de
moteur "api" pour cet agent.
"""
import argparse
import json
from datetime import date
from pathlib import Path

from agents.llm_service import ClaudeCodeLLMService, LLMUnavailable
from utils.db_utils import MySQLUtils
from utils.display_utils import HIDDEN_SPOT_TYPES, spot_name_label
from utils.logger_util import LoggerUtil
from utils.service_utils import ServiceUtil

logger = LoggerUtil.get_logger("etl_verify_spots")


# =============================================================================
# 1. CE QU'ON DEMANDE À CLAUDE
# =============================================================================

# Version des consignes. À AUGMENTER À CHAQUE MODIFICATION DU PROMPT.
#   1 : version initiale
#   2 : date du jour fournie ; une période terminée n'est plus valable ; effort élevé
#   3 : état actuel de la fiche Park4Night (ouverture, type) et commentaires récents
#       fournis ; une période terminée ne prouve pas une réouverture ; "plus_valable"
#       seulement si TOUTES les situations signalées ont pris fin
#   4 : pas de tarif chiffré dans le résumé ; une règle communale se juge sur
#       l'ensemble des spots de la commune, via l'outil MCP temoignages_commune
VERIFY_PROMPT_VERSION = 4

# Nombre de commentaires récents transmis à l'agent (les plus récents d'abord).
RECENT_REVIEWS = 5

# Nos propres outils, branchés par MCP (agents/mcp_randovango.py). L'agent les
# appelle seulement s'il en a besoin, au lieu de recevoir toutes ces informations
# d'office (trop d'informations inutiles risqueraient de le perdre).
MCP_SERVERS = {
    "randovango": {
        "command": "python",
        "args": [str(Path(__file__).resolve().parent / "mcp_randovango.py")],
    },
}
# Nom complet d'un outil MCP pour la CLI : mcp__<serveur>__<outil>.
MCP_TOOLS = ["mcp__randovango__temoignages_commune"]

# Effort de réflexion. L'harmonisation se contente de "low" ; une recherche web
# a besoin de plus (en "low", l'agent répondait sans vraiment chercher). L'agent
# ne traite que les spots marqués a_verifier : on peut se le permettre.
VERIFY_EFFORT = "high"

# Outils autorisés : chercher sur le web et lire des pages. Rien d'autre.
WEB_TOOLS = ["WebSearch", "WebFetch"]

# Une recherche web prend du temps (souvent 30 s à 1 min) : délai plus long.
VERIFY_TIMEOUT_SECONDS = 400

VERIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "statut": {
            "type": "string",
            "enum": ["toujours_valable", "plus_valable", "incertain"],
        },
        "resume": {
            "type": "string",
            "description": "Une à trois phrases neutres, au présent, chaque fait daté.",
        },
        "sources": {
            "type": "array",
            "items": {"type": "string"},
            "description": "URL des pages réellement consultées qui appuient le statut.",
        },
    },
    "required": ["statut", "resume", "sources"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """Tu vérifies des informations de fiches de stationnement pour Randovango, une application
de voyage en van. Une fiche Park4Night signale une ou plusieurs situations temporaires (fermeture,
travaux, interdiction récente, équipement en panne). Tu dis si elles sont toujours d'actualité.

## Méthode, dans cet ordre
1. L'état actuel de la fiche Park4Night (type, ouverture), relu récemment, est la source la plus
   fiable : s'il indique toujours une fermeture, la fermeture dure.
2. La date du jour : si une information porte sur une période déjà terminée ("interdit jusqu'en
   septembre" alors qu'on est en octobre), cette période est finie. Mais la fin d'une période ne
   prouve pas une réouverture : un lieu "fermé pour la saison" peut rester fermé ensuite.
3. Les commentaires récents de la fiche : un voyageur peut confirmer ou démentir la situation.
   Une règle qui peut concerner toute la commune (interdiction de nuit des camping-cars,
   contrôles de police) se juge sur l'ensemble de ses spots : dans ce cas, et seulement dans ce
   cas, appelle l'outil temoignages_commune avec l'identifiant du spot avant de conclure. Les
   témoignages des autres spots montrent si la règle est saisonnière (contrôles seulement en
   été, pas de panneau hors saison) ou permanente.
4. En dernier recours seulement, le web : sources datées, de préférence officielles et récentes
  (site de la commune, arrêtés municipaux, site du lieu, presse locale, avis datés d'autres
  applications de voyage en van).
- Une source n'est utile que si elle est postérieure au signalement ou si elle le confirme.
- Vérifie que la source parle bien du même lieu (adresse, coordonnées), et non d'un lieu voisin.
- N'utilise pas tes connaissances : uniquement ce que tu trouves pendant la recherche.

## statut
- "toujours_valable" : une source récente confirme qu'au moins une des situations dure.
- "plus_valable" : TOUTES les situations signalées ont pris fin (période terminée sans fermeture
  persistante, réouverture, travaux terminés, interdiction levée, équipement réparé), ou le lieu a
  changé (déplacement, fermeture définitive).
- "incertain" : rien de récent et fiable, ou seulement une partie des situations a pris fin. C'est
  la réponse attendue en cas de doute ; le résumé dit alors ce qui a pris fin et ce qui n'a pas pu
  être confirmé.

## resume
Une à trois phrases pour le voyageur, neutres, au présent, à la troisième personne. Chaque fait est
daté ("en septembre 2026, ..."). Pas de "je", pas de conseil, pas de numéro de téléphone, pas de
tarif chiffré, pas de commentaire sur ta recherche. Si le statut est "incertain", dis seulement que l'information n'a pas
pu être confirmée.

## sources
Les URL des pages consultées qui appuient le statut. Liste vide si "incertain", ou si le statut ne
repose que sur une période terminée.

Réponds en français."""


def build_user_message(spot: dict) -> str:
    """
    Écrit le message envoyé à Claude : de quoi identifier le lieu sur le web, et
    l'information à vérifier (le paragraphe « À savoir » de la fiche harmonisée).
    Ici le contexte géographique est nécessaire : c'est lui qui permet de chercher.
    """
    description = spot.get("description_ia") or ""
    to_check = description.split("À savoir :", 1)[1].strip() if "À savoir :" in description else description
    read_on = spot.get("details_scraped_at")
    lines = [
        f"DATE DU JOUR : {date.today().strftime('%d/%m/%Y')}",
        f"IDENTIFIANT DU SPOT : {spot['id']}",
        f"LIEU : {spot['name_label']}",
        f"COMMUNE : {spot.get('city_label') or 'inconnue'} ({spot.get('postal_code') or 'code postal inconnu'})",
        f"COORDONNÉES : {spot['latitude']}, {spot['longitude']}",
        f"FICHE PARK4NIGHT : {spot.get('url') or 'inconnue'}",
        f"ÉTAT ACTUEL DE LA FICHE (relue le {read_on.strftime('%d/%m/%Y') if read_on else 'date inconnue'}) :",
        f"- type : {spot.get('type') or 'inconnu'}",
        f"- ouverture : {spot.get('opening_period') or 'non renseignée'}",
        f"INFORMATION À VÉRIFIER : {to_check}",
        "COMMENTAIRES RÉCENTS DE LA FICHE :",
    ]
    reviews = spot.get("recent_reviews") or []
    if not reviews:
        lines.append("(aucun)")
    for review in reviews:
        day = review["review_date"].strftime("%d/%m/%Y") if review.get("review_date") else "date inconnue"
        text = (review.get("text") or "").replace("\n", " ").strip()
        lines.append(f'- {day} : "{text}"')
    return "\n".join(lines)


# =============================================================================
# 2. LIRE ET ÉCRIRE DANS LA BASE MYSQL
# =============================================================================

def create_verification_table(cursor) -> None:
    """Crée la table des vérifications si elle n'existe pas (sans risque si elle existe)."""
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS spot_verifications (
            id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
            spot_id INT NOT NULL,
            verified_at DATETIME NOT NULL,
            statut VARCHAR(20) NOT NULL,
            resume TEXT,
            sources JSON,
            prompt_version INT,
            model VARCHAR(50),
            FOREIGN KEY (spot_id) REFERENCES spots(id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)


def fetch_spots_to_verify(cursor, limit: int = None, spot_ids: list = None) -> list:
    """
    Spots marqués `a_verifier` à (re)vérifier : jamais vérifiés depuis leur
    dernière harmonisation, ou vérifiés avec une ancienne version du prompt.
    Les types masqués (ex : "PARKING JOUR UNIQUEMENT") sont ignorés.
    `spot_ids` (option --id) : ces spots-là, sans condition.
    Chaque spot contient aussi ses commentaires les plus récents ("recent_reviews").
    """
    columns = """
        s.id, s.name, s.type, s.place_label, s.city_label, s.postal_code,
        s.latitude, s.longitude, s.url, s.description_ia, s.opening_period, s.details_scraped_at
    """
    if spot_ids:
        placeholders = ",".join(["%s"] * len(spot_ids))
        cursor.execute(f"SELECT {columns} FROM spots s WHERE s.id IN ({placeholders}) ORDER BY s.id",
                       tuple(spot_ids))
    else:
        type_placeholders = ",".join(["%s"] * len(HIDDEN_SPOT_TYPES))
        query = f"""
            SELECT {columns}
            FROM spots s
            WHERE s.a_verifier = 1
              AND s.p4n_removed = 0
              AND s.duplicate_of_spot_id IS NULL
              AND s.type NOT IN ({type_placeholders})
              AND NOT EXISTS (
                  SELECT 1 FROM spot_verifications v
                  WHERE v.spot_id = s.id
                    AND v.verified_at >= s.harmonized_at
                    AND v.prompt_version >= %s
              )
            ORDER BY s.id
        """
        params = (*HIDDEN_SPOT_TYPES, VERIFY_PROMPT_VERSION)
        if limit:
            query += " LIMIT %s"
            params = (*params, limit)
        cursor.execute(query, params)

    column_names = [column[0] for column in cursor.description]
    spots = []
    for row in cursor.fetchall():
        spot = dict(zip(column_names, row))
        spot["name_label"] = spot_name_label(spot["place_label"], spot["city_label"], spot["name"], spot["type"])
        spots.append(spot)
    attach_recent_reviews(cursor, spots)
    logger.info(f"[verify] {len(spots)} spot(s) à vérifier")
    return spots


def attach_recent_reviews(cursor, spots: list) -> None:
    """Ajoute à chaque spot ses RECENT_REVIEWS commentaires les plus récents."""
    for spot in spots:
        cursor.execute(
            "SELECT review_date, text FROM spot_reviews WHERE spot_id = %s"
            " ORDER BY review_date DESC LIMIT %s",
            (spot["id"], RECENT_REVIEWS),
        )
        spot["recent_reviews"] = [{"review_date": day, "text": text} for day, text in cursor.fetchall()]


def write_verification(cursor, spot_id: int, payload: dict, model: str) -> None:
    """Enregistre une vérification (une nouvelle ligne : on garde l'historique)."""
    cursor.execute(
        """
        INSERT INTO spot_verifications (spot_id, verified_at, statut, resume, sources, prompt_version, model)
        VALUES (%s, NOW(), %s, %s, %s, %s, %s)
        """,
        (
            spot_id, payload["statut"], payload["resume"].strip(),
            json.dumps(payload.get("sources") or [], ensure_ascii=False),
            VERIFY_PROMPT_VERSION, model,
        ),
    )


# =============================================================================
# 3. LANCEMENT
# =============================================================================

def run(limit: int = None, spot_ids: list = None) -> None:
    """Vérifie les spots un par un ; chaque résultat est enregistré dès qu'il arrive."""
    service = ClaudeCodeLLMService(
        tools=WEB_TOOLS, mcp_servers=MCP_SERVERS, mcp_tools=MCP_TOOLS,
        timeout=VERIFY_TIMEOUT_SECONDS, effort=VERIFY_EFFORT,
    )

    ServiceUtil.load_env()
    connection = MySQLUtils.connect()
    cursor = connection.cursor()
    create_verification_table(cursor)
    connection.commit()

    counts = {"toujours_valable": 0, "plus_valable": 0, "incertain": 0, "erreur": 0}
    try:
        for spot in fetch_spots_to_verify(cursor, limit=limit, spot_ids=spot_ids):
            try:
                payload = service.complete_json(SYSTEM_PROMPT, build_user_message(spot), VERIFY_SCHEMA)
            except (LLMUnavailable, json.JSONDecodeError) as error:
                counts["erreur"] += 1
                logger.warning(f"[verify] #{spot['id']} non vérifié, retenté au prochain lancement : {error}")
                continue
            write_verification(cursor, spot["id"], payload, service.model)
            connection.commit()
            counts[payload["statut"]] += 1
            logger.info(
                f"[verify] #{spot['id']} {spot['name_label']} -> {payload['statut'].upper()}"
                f" ({(service.last_run.get('duration_ms') or 0) / 1000:.0f} s,"
                f" {service.last_run.get('turns')} tours,"
                f" outils : {', '.join(service.last_run.get('tools') or []) or 'aucun'}) : {payload['resume']}"
                f" | sources : {', '.join(payload.get('sources') or []) or 'aucune'}"
            )
    finally:
        cursor.close()
        MySQLUtils.disconnect(connection)

    logger.info(f"[verify] Terminé : {counts}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sample", type=int, help="Vérifier N spots")
    parser.add_argument("--all", action="store_true", help="Vérifier tous les spots en attente")
    parser.add_argument("--id", type=int, nargs="+", metavar="SPOT_ID", help="Vérifier ces spots précis")
    args = parser.parse_args()

    if args.id:
        run(spot_ids=args.id)
    elif args.sample:
        run(limit=args.sample)
    elif args.all:
        run()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
