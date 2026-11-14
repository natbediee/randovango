"""
Lecture des périodes d'ouverture des spots par un agent.

La fiche p4n donne l'ouverture en texte libre, dans toutes les langues et tous les formats
("Closed from mid-september", "Du 15 septembre au 15 juin", "Pâques à la toussaint"). L'agent le
traduit en dates sans année, rangées à côté du texte d'origine, qui n'est jamais modifié.

Cet agent ne décide pas si un spot est proposé : c'est services/spot_selection_service.py qui
compare ces dates à la date de la nuit.

ON NE REFAIT PAS LE TRAVAIL DEUX FOIS
`ouverture_lue` garde le texte traduit : un spot n'est relu que si le texte de sa fiche a changé.
"Ouvert toute l'année", le texte le plus courant, ne demande aucun appel : sans dates, un spot
est proposé.

LA DÉCISION HUMAINE PRIME
Un spot dont l'ouverture a été tranchée par un humain (table `decisions`, voir /supervision) n'est
jamais relu, même avec --id ou si le texte de sa fiche change. /supervision signale ce changement ;
annuler la décision rend le spot à cet agent.

UTILISATION (dans le conteneur backend, depuis /usr/src/app)
    python -m agents.read_openings --sample 20
    python -m agents.read_openings --all
    python -m agents.read_openings --id 1384 670
"""
import argparse
import json
import re
from datetime import date

from agents.llm_config import make_llm_service
from agents.llm_service import LLMUnavailable, mesure_objet
from services.supervision.spots_review import OPENING_OBJECT
from utils.db_utils import MySQLUtils
from utils.display_utils import HIDDEN_SPOT_TYPES
from utils.logger_util import LoggerUtil

logger = LoggerUtil.get_logger("etl_read_openings")

ALL_YEAR = "Ouvert toute l'année"
TOUTE_ANNEE, PERIODE, SAISON, INCONNUE = "toute_annee", "periode", "saison", "inconnue"
MAX_DESCRIPTION_CHARS = 1000
MONTH_DAY = re.compile(r"(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])")
MAX_FAILURES_IN_A_ROW = 3
NOT_DECIDED_BY_HUMAN = f"""NOT EXISTS (SELECT 1 FROM decisions d WHERE d.objet_type = '{OPENING_OBJECT}'
                                       AND d.objet_id = spots.id AND d.annulee_at IS NULL)"""

OPENING_SCHEMA = {
    "type": "object",
    "properties": {
        "statut": {"type": "string", "enum": [TOUTE_ANNEE, PERIODE, SAISON, INCONNUE]},
        "debut": {"type": ["string", "null"], "description": "Premier jour d'ouverture, MM-JJ, ou null."},
        "fin": {"type": ["string", "null"], "description": "Dernier jour d'ouverture, MM-JJ, ou null."},
    },
    "required": ["statut", "debut", "fin"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """Tu lis la période d'ouverture d'un lieu de stationnement pour van, écrite en texte libre sur
une fiche Park4Night, dans n'importe quelle langue. Tu reçois ce texte, la description de la fiche et la date du
jour. Ta réponse sert à ne pas proposer le lieu pour une nuit où il est fermé : une date inventée ferait disparaître
un lieu ouvert. Ne devine jamais.

## statut
- toute_annee : ouvert toute l'année, même avec une exception d'un jour ou deux.
- periode : le lieu ferme une partie de l'année, et le texte permet de dire quand.
- saison : le lieu ferme chaque année, le texte l'indique clairement mais sans date.
- inconnue : tout le reste.

## description
Elle sert seulement à comprendre le texte d'ouverture, et à ne pas le prendre à tort pour une fermeture du lieu.
Réponds inconnue si elle montre que :
- le texte parle d'un équipement et non du lieu ("Not available in winter" et "La borne est hors service en hiver") ;
- le lieu ne ferme pas ("Summer season" et "Ouvert toute l'année") ;
- la fermeture ne vaut que pour une année ("Closed from 8/8 to 22/8" et "Fermé du 8 au 22 août 2026").
Une description seule, sans rapport avec le texte d'ouverture, ne change pas ta réponse.

## periode : debut et fin
Le premier et le dernier jour où l'on peut dormir sur place, au format MM-JJ, sans année.
- Si le texte donne la fermeture, donne son contraire : "Fermé du 1 novembre au 31 mars" donne debut 04-01,
  fin 10-31. La période peut passer par le 1er janvier : "Du 15 septembre au 15 juin" donne debut 09-15, fin 06-15.
- Une interdiction de dormir sur une période de l'année se lit comme une fermeture : "Interdit la nuit du 01/06 au
  30/09" donne debut 10-01, fin 05-31.
- Si une seule borne est connue, l'autre vaut null : "Closed from mid-september" donne debut null, fin 09-15.
- Un mois seul va du 1er au dernier jour : "Avril à septembre" donne debut 04-01, fin 09-30. "début" est le 1er,
  "mi" le 15, "fin" le dernier jour du mois.
- Une saison ou une fermeture d'hiver qui porte une année se lit sans l'année, même si cette année est passée : une
  saison bouge peu d'une année à l'autre. "From may 16 to september 14, 2025" donne debut 05-16, fin 09-14.

## saison : debut et fin valent null
"En saison", "Open in season", "Fermé l'hiver", "Closed in winter", "Summer season", "Été", "Pâques à la toussaint".

## inconnue : debut et fin valent null
- texte vide, illisible, ou sans rapport avec l'ouverture (marché, barrière, durée de séjour) ;
- horaires ou jours de la semaine ("10h-17h", "Closed on sundays") ;
- fermeture temporaire, travaux, panne, ou fermeture ponctuelle liée à un événement ("Temporarily closed",
  "Parking prohibited from may 19 to 21 due to a fair") ;
- période sans saison claire ("Hors saison", "vacances scolaires", "voir le site") ;
- le texte parle d'un équipement et non du lieu ("Sanitaires ouverts en période estivale", "Service closed for
  winter") ;
- fermeture d'une seule année, qui ne revient pas chaque année ("Closed until september 2025", "Closed from 18.06
  until 5.09.2026", "Fermé, réouverture en mai 2027")."""


def build_user_message(opening_period: str, description: str | None = None) -> str:
    return (f'DATE DU JOUR : {date.today():%d/%m/%Y}\nOUVERTURE : "{opening_period}"\n'
            f'DESCRIPTION : "{(description or "")[:MAX_DESCRIPTION_CHARS]}"')


def read_opening(service, opening_period: str, description: str | None = None) -> dict:
    return service.complete_json(SYSTEM_PROMPT, build_user_message(opening_period, description), OPENING_SCHEMA)


def _month_day(value) -> str | None:
    return value if isinstance(value, str) and MONTH_DAY.fullmatch(value) else None


def normalize(payload: dict) -> dict:
    """Une date mal formée ne doit jamais fermer un spot : sans date valable, la période est inconnue."""
    status = payload.get("statut")
    if status == SAISON:
        return {"statut": SAISON, "debut": None, "fin": None}
    if status != PERIODE:
        return {"statut": status if status == TOUTE_ANNEE else INCONNUE, "debut": None, "fin": None}
    start, end = _month_day(payload.get("debut")), _month_day(payload.get("fin"))
    if not start and not end:
        return {"statut": INCONNUE, "debut": None, "fin": None}
    return {"statut": PERIODE, "debut": start, "fin": end}


def fetch_spots_to_read(cursor, limit: int = None, spot_ids: list = None) -> list:
    """Les spots dont le texte d'ouverture n'a pas encore été lu, ou a changé depuis, sauf décision humaine."""
    if spot_ids:
        placeholders = ",".join(["%s"] * len(spot_ids))
        cursor.execute(f"SELECT id, opening_period, description FROM spots WHERE id IN ({placeholders})"
                       f" AND {NOT_DECIDED_BY_HUMAN} ORDER BY id", tuple(spot_ids))
        return [{"id": row[0], "opening_period": row[1], "description": row[2]}
                for row in cursor.fetchall() if row[1]]
    placeholders = ",".join(["%s"] * len(HIDDEN_SPOT_TYPES))
    query = f"""
        SELECT id, opening_period, description FROM spots
        WHERE opening_period IS NOT NULL AND opening_period <> '' AND opening_period <> %s
          AND (ouverture_lue IS NULL OR ouverture_lue <> opening_period)
          AND duplicate_of_spot_id IS NULL AND p4n_removed = 0
          AND type IS NOT NULL AND type NOT IN ({placeholders})
          AND {NOT_DECIDED_BY_HUMAN}
        ORDER BY id
    """
    params = (ALL_YEAR, *HIDDEN_SPOT_TYPES)
    if limit:
        query += " LIMIT %s"
        params = (*params, limit)
    cursor.execute(query, params)
    return [{"id": row[0], "opening_period": row[1], "description": row[2]} for row in cursor.fetchall()]


def write_opening(cursor, spot_id: int, opening_period: str, payload: dict) -> None:
    fields = normalize(payload)
    cursor.execute(
        """
        UPDATE spots
        SET ouverture_statut = %s, ouverture_debut = %s, ouverture_fin = %s, ouverture_lue = %s
        WHERE id = %s
        """,
        (fields["statut"], fields["debut"], fields["fin"], opening_period, spot_id),
    )


def run(limit: int = None, spot_ids: list = None, service=None) -> None:
    """Un spot à la fois, enregistré aussitôt : un arrêt en route ne perd rien."""
    if service is None:
        service = make_llm_service("read_openings")
    connection = MySQLUtils.connect()
    cursor = connection.cursor()
    failures_in_a_row = 0
    try:
        spots = fetch_spots_to_read(cursor, limit, spot_ids)
        logger.info(f"[ouvertures] {len(spots)} spot(s) à lire")
        for spot in spots:
            try:
                with mesure_objet("spot", spot.get("id")):
                    payload = read_opening(service, spot["opening_period"], spot["description"])
            except (LLMUnavailable, json.JSONDecodeError) as error:
                logger.warning(f"[ouvertures] Spot {spot['id']} ignoré : {error}")
                failures_in_a_row += 1
                if failures_in_a_row >= MAX_FAILURES_IN_A_ROW:
                    logger.error(f"[ouvertures] {failures_in_a_row} échecs de suite : arrêt, relancer plus tard")
                    break
                continue
            failures_in_a_row = 0
            write_opening(cursor, spot["id"], spot["opening_period"], payload)
            connection.commit()
            logger.info(f"[ouvertures] #{spot['id']} {spot['opening_period']!r} -> {normalize(payload)}")
    finally:
        cursor.close()
        MySQLUtils.disconnect(connection)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sample", type=int, help="Lire N spots")
    parser.add_argument("--all", action="store_true", help="Lire tous les spots en attente")
    parser.add_argument("--id", type=int, nargs="+", metavar="SPOT_ID", help="Lire ces spots précis")
    args = parser.parse_args()
    if not (args.sample or args.all or args.id):
        parser.error("indiquer --sample, --all ou --id")
    run(args.sample, args.id)


if __name__ == "__main__":
    main()
