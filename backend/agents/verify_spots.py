"""
Vérification sur le web des informations temporaires des spots.

C'est une transformation POST-CHARGEMENT (voir agents/__init__.py), qui
vient APRÈS l'harmonisation : celle-ci marque `a_verifier = 1` les spots dont la
fiche signale une situation temporaire décisive (fermeture, travaux, interdiction
récente, équipement en panne). Cet agent cherche sur le web si elle est toujours
d'actualité.

CE N'EST PAS DE L'HARMONISATION, C'EST DE L'ENRICHISSEMENT
Le web est une source externe à p4n. Le résultat est donc rangé à part,
dans la table `spot_verifications` (statut, résumé, sources, date), et la fiche
du spot n'est jamais modifiée, sauf son badge : un doute de l'agent le passe en
« non vérifié » (mark_doubt). On garde l'historique : une ligne par vérification.

LES COMMENTAIRES REFONT L'HISTOIRE
La base ne garde qu'un échantillon des commentaires, qui favorise les plus mauvais : une
plainte y reste, pas toujours le commentaire qui dit que c'est réparé. L'agent relit donc
sur p4n tous ceux des 12 derniers mois (read_recent_reviews). Il rend :
    - "a_savoir" : le paragraphe « À savoir » tel qu'il doit être affiché aujourd'hui,
      phrase par phrase, avec la période de l'année des règles saisonnières ;
    - "utilisable" : peut-on y passer la nuit aujourd'hui ? Dans le doute, non : on préfère
      ne pas proposer un lieu risqué. "utilisable_a_partir" : la réouverture annoncée.

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
import re
from datetime import date, timedelta
from pathlib import Path

from agents.llm_config import make_llm_service
from agents.llm_service import LLMUnavailable
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
#   3 : état actuel de la fiche p4n (ouverture, type) et commentaires récents
#       fournis ; une période terminée ne prouve pas une réouverture ; "plus_valable"
#       seulement si TOUTES les situations signalées ont pris fin
#   4 : pas de tarif chiffré dans le résumé ; une règle communale se juge sur
#       l'ensemble des spots de la commune, via l'outil MCP temoignages_commune
#   5 : "À savoir" corrigé phrase par phrase, avec la période des règles saisonnières ;
#       lieu utilisable ou non ; commentaires des 12 derniers mois. Une information n'est
#       retirée que sur preuve : l'absence de nouvelles n'en est pas une
VERIFY_PROMPT_VERSION = 5

MAX_FAILURES_IN_A_ROW = 3

# Commentaires transmis à l'agent : ceux des 12 derniers mois, relus sur p4n,
# les plus récents d'abord. Une fiche très commentée en a des centaines.
REVIEWS_DAYS = 365
MAX_REVIEWS = 40
# Si la fiche n'a rien de récent ou ne peut pas être relue : les derniers commentaires en base.
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
        "a_savoir": {
            "type": "array",
            "description": "Le paragraphe « À savoir » à afficher aujourd'hui, une phrase par information.",
            "items": {
                "type": "object",
                "properties": {
                    "texte": {"type": "string"},
                    "debut": {"type": ["string", "null"], "description": "Début de la période annuelle, MM-JJ."},
                    "fin": {"type": ["string", "null"], "description": "Fin de la période annuelle, MM-JJ."},
                },
                "required": ["texte", "debut", "fin"],
                "additionalProperties": False,
            },
        },
        "utilisable": {"type": "string", "enum": ["oui", "non"]},
        "utilisable_a_partir": {"type": ["string", "null"], "description": "Date de réouverture, AAAA-MM-JJ."},
        "raison": {"type": "string", "description": "Pourquoi le lieu n'est pas utilisable, en une phrase datée."},
    },
    "required": ["statut", "resume", "sources", "a_savoir", "utilisable", "utilisable_a_partir", "raison"],
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

## a_savoir
Réécris le paragraphe « À savoir » de la fiche tel qu'il doit être affiché aujourd'hui, sous forme d'une liste
de phrases courtes, une par information. Élément par élément :
- Retire une information seulement sur preuve : un commentaire plus récent la dément, ou elle porte sur une
  période terminée qui ne revient pas. L'absence de nouvelles n'est pas une preuve : garde l'information, datée.
- Un commentaire plus récent qui dit que c'est réparé ou qui dément le problème l'emporte.
- Garde ce qui est durable (règles, durée de séjour, accès, contrôles, sécurité, nuisances répétées).
- Date ce qui est temporaire ("signalé en juillet 2026") ; décris la situation actuelle, pas son historique.
- Tu peux ajouter une situation temporaire récente qui change la décision de venir (panne, fermeture, interdiction),
  trouvée dans les commentaires. N'ajoute rien d'autre : pas de description du lieu (places, vue, plage), pas de
  rumeur ou de projet, ne parle pas de tes sources.
Pour une règle ou une situation qui revient chaque année à la même période (chiens interdits sur la plage en été),
donne ses dates dans "debut" et "fin" au format MM-JJ et ne les répète pas dans le texte si elles sont claires ;
"debut" et "fin" valent null pour tout le reste, ou si la fiche ne donne qu'une des deux bornes : la borne manquante
vaut null. Liste vide s'il ne reste rien.

## utilisable
"non" si, à la date du jour, on ne peut pas venir passer la nuit avec un van : accès bloqué, lieu fermé, interdiction de
nuit aux camping-cars, sans démenti plus récent, même si le signalement est ancien : dans le doute, on préfère ne
pas proposer un lieu risqué. Une fermeture de saison qui reviendra chaque année se traite dans "debut"/"fin", pas ici.
"oui" sinon : une panne d'un équipement, une partie fermée (station de lavage, douches), un manque de services ou une
limite de hauteur ou de longueur (elle dépend du véhicule : garde-la dans a_savoir) ne rend pas le lieu inutilisable.
"utilisable_a_partir" : la date de réouverture annoncée (AAAA-MM-JJ) si le lieu est "non" ; si seul le mois est annoncé
("mai 2027"), le premier jour de ce mois (2027-05-01). Sinon null.
"raison" : pourquoi "non", en une phrase datée ; chaîne vide si "oui".

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

def fetch_spots_to_verify(cursor, limit: int = None, spot_ids: list = None, only_new: bool = False) -> list:
    """
    Spots marqués `a_verifier` à (re)vérifier : jamais vérifiés depuis leur
    dernière harmonisation, ou vérifiés avec une ancienne version du prompt.
    Les types masqués (ex : "PARKING JOUR UNIQUEMENT") sont ignorés.
    `spot_ids` (option --id) : ces spots-là, sans condition.
    `only_new` (ETL) : seulement les spots jamais vérifiés. Revérifier les anciens
    sur une nouvelle version du prompt reste une décision, pas un effet du scraping.
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
        recent = "" if only_new else "AND v.verified_at >= s.harmonized_at AND v.prompt_version >= %s"
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
                    {recent}
              )
            ORDER BY s.id
        """
        params = HIDDEN_SPOT_TYPES if only_new else (*HIDDEN_SPOT_TYPES, VERIFY_PROMPT_VERSION)
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


def recent_reviews(reviews: list, today: date) -> list:
    """Les commentaires des 12 derniers mois, les plus récents d'abord, MAX_REVIEWS au plus."""
    cutoff = today - timedelta(days=REVIEWS_DAYS)
    dated = [review for review in reviews if review.get("review_date") and review["review_date"] >= cutoff]
    return sorted(dated, key=lambda review: review["review_date"], reverse=True)[:MAX_REVIEWS]


def read_recent_reviews(driver, wait, spot: dict, first_page: bool = False) -> None:
    """
    Remplace les commentaires du spot par ceux des 12 derniers mois, relus sur p4n.
    La base n'en garde qu'un échantillon. Si la fiche ne peut pas être relue ou n'a rien de
    récent, l'agent garde les derniers commentaires en base (attach_recent_reviews).
    """
    from selenium.common.exceptions import WebDriverException
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC

    from etl.extract.scraper_p4n import dismiss_cookies, extract_reviews

    try:
        driver.get(spot["url"])
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "h1.place-header-name")))
        if first_page:
            dismiss_cookies(driver, wait)   # le bandeau n'apparaît qu'à la première page
        spot["recent_reviews"] = recent_reviews(extract_reviews(driver), date.today()) or spot["recent_reviews"]
    except WebDriverException as error:
        logger.warning(f"[verify] #{spot['id']} fiche non relue, commentaires en base : {error}")


def clean_a_savoir(items: list) -> list:
    """Phrases non vides ; une période mal formée est retirée, la phrase reste."""
    def month_day(value):
        return value if value and re.fullmatch(r"(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])", value) else None
    return [{"texte": item["texte"].strip(), "debut": month_day(item.get("debut")), "fin": month_day(item.get("fin"))}
            for item in items if (item.get("texte") or "").strip()]


def clean_reopening(value: str | None) -> str | None:
    """La date de réouverture, si elle est lisible ; sinon None : le lieu reste non utilisable."""
    try:
        return date.fromisoformat(value).isoformat() if value else None
    except ValueError:
        return None


def write_verification(cursor, spot_id: int, payload: dict, model: str) -> None:
    """Enregistre une vérification (une nouvelle ligne : on garde l'historique)."""
    usable = payload["utilisable"] == "oui"
    cursor.execute(
        """
        INSERT INTO spot_verifications (spot_id, verified_at, statut, resume, sources, prompt_version, model,
                                        a_savoir, utilisable, utilisable_a_partir, raison)
        VALUES (%s, NOW(), %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            spot_id, payload["statut"], payload["resume"].strip(),
            json.dumps(payload.get("sources") or [], ensure_ascii=False),
            VERIFY_PROMPT_VERSION, model,
            json.dumps(clean_a_savoir(payload["a_savoir"]), ensure_ascii=False),
            payload["utilisable"],
            None if usable else clean_reopening(payload.get("utilisable_a_partir")),
            None if usable else (payload.get("raison") or "").strip(),
        ),
    )


def is_doubtful(payload: dict) -> bool:
    """L'agent a un doute sur le lieu : rien de récent et fiable, ou lieu non utilisable."""
    return payload["statut"] == "incertain" or payload["utilisable"] == "non"


def mark_doubt(cursor, spot_id: int) -> None:
    """
    Un doute de l'agent retire le badge « Vérifié » du spot. Seule modification de la fiche,
    et seulement dans ce sens : l'absence de doute ne suffit pas à déclarer un lieu vérifié.
    """
    cursor.execute("UPDATE spots SET verifie = 0 WHERE id = %s", (spot_id,))


# =============================================================================
# 3. LANCEMENT
# =============================================================================

def run(limit: int = None, spot_ids: list = None, only_new: bool = False) -> None:
    """Vérifie les spots un par un ; chaque résultat est enregistré dès qu'il arrive."""
    service = make_llm_service("verify_spots", mcp_servers=MCP_SERVERS, mcp_tools=MCP_TOOLS)

    ServiceUtil.load_env()
    connection = MySQLUtils.connect()
    cursor = connection.cursor()

    spots = fetch_spots_to_verify(cursor, limit=limit, spot_ids=spot_ids, only_new=only_new)
    if not spots:  # l'ETL passe ici à chaque ville : pas de navigateur pour rien
        cursor.close()
        MySQLUtils.disconnect(connection)
        return

    from selenium.webdriver.support.ui import WebDriverWait

    from etl.extract.scraper_p4n import create_driver

    driver = create_driver()
    wait = WebDriverWait(driver, 15)

    counts = {"toujours_valable": 0, "plus_valable": 0, "incertain": 0, "erreur": 0, "non_utilisable": 0}
    failures_in_a_row = 0
    try:
        for number, spot in enumerate(spots):
            read_recent_reviews(driver, wait, spot, first_page=number == 0)
            try:
                payload = service.complete_json(SYSTEM_PROMPT, build_user_message(spot), VERIFY_SCHEMA)
            except (LLMUnavailable, json.JSONDecodeError) as error:
                counts["erreur"] += 1
                logger.warning(f"[verify] #{spot['id']} non vérifié, retenté au prochain lancement : {error}")
                failures_in_a_row += 1
                # Quota atteint ou agent en panne : inutile de relire les fiches suivantes.
                if failures_in_a_row >= MAX_FAILURES_IN_A_ROW:
                    logger.error(f"[verify] {failures_in_a_row} échecs de suite : arrêt, relancer plus tard")
                    break
                continue
            failures_in_a_row = 0
            write_verification(cursor, spot["id"], payload, service.model)
            if is_doubtful(payload):
                mark_doubt(cursor, spot["id"])
            connection.commit()
            counts[payload["statut"]] += 1
            counts["non_utilisable"] += payload["utilisable"] == "non"
            logger.info(
                f"[verify] #{spot['id']} {spot['name_label']} -> {payload['statut'].upper()},"
                f" utilisable : {payload['utilisable']}"
                f" ({(service.last_run.get('duration_ms') or 0) / 1000:.0f} s,"
                f" {service.last_run.get('turns')} tours,"
                f" outils : {', '.join(service.last_run.get('tools') or []) or 'aucun'}) : {payload['resume']}"
                f" | sources : {', '.join(payload.get('sources') or []) or 'aucune'}"
            )
    finally:
        driver.quit()
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
