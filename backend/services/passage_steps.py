"""
Les étapes de la file des passages, et ce dont chacune dépend pour une ville (issue #332).

POURQUOI DES ÉTAPES
Avant #332, la file prenait les passages chaîne par chaîne pour toutes les villes : aucun agent ne tournait tant qu'il
restait un OSM en file, et chaque nouvel envoi de randos repoussait les agents des villes déjà en file. Désormais,
chaque étape a sa file et son fil de fond (services/passage_queue.py) : elle prend une ville à la fois, dans l'ordre
d'envoi, et n'attend jamais les étapes qui viennent après elle.

UNE ÉTAPE, CE SONT DES PARTIES D'UNE CHAÎNE
La plupart des étapes sont une chaîne entière (OSM, carburants, FINESS, pépites, services). La chaîne des spots, elle,
se coupe en deux étapes : la lecture de la source (gratuite, un navigateur à la fois), puis ses trois agents payants
(harmonisation, ouvertures, vérification). Le passage des spots reste un seul passage : l'étape « source » fait sa
première partie, le remet en file, et l'étape des agents des spots le prend ensuite.
L'étape d'un passage en file se lit donc dans sa prochaine partie à faire (step_for).

CE DONT UNE ÉTAPE DÉPEND, VILLE PAR VILLE
    dès l'envoi                       OSM et Wikidata, lecture de la source des spots
    après OSM et Wikidata de la ville carburants, FINESS, pépites, services
    après la lecture de la source     agents des spots (harmonisation, puis ouvertures, puis vérification)
Une ville dont l'étape d'avant n'est pas finie attend, pour elle seule : l'étape prend la ville suivante qui est prête.
"""
from dataclasses import dataclass

from services import passage_store, service_store, spot_chain


@dataclass(frozen=True)
class Step:
    """Une étape de la file : des parties d'une chaîne, et ce dont elle dépend pour une ville."""
    key: str
    label: str
    chain: str                  # la chaîne des passages que l'étape fait tourner
    parts: tuple | None         # ses parties dans la chaîne ; None : toutes les parties de la chaîne
    paid: bool                  # payante : elle attend le quota et le budget des agents
    needs: tuple | None = None  # (chaîne, partie) qui doit être finie pour la ville avant elle ; None : rien


OSM_DONE = ("osm", "osm")                   # la partie unique de la chaîne OSM (OSM puis Wikidata)
SOURCE_DONE = ("spots", "source")           # la lecture de la source des spots

# L'ordre de cette liste est celui des fils de fond au démarrage ; il ne décide d'aucune priorité entre étapes.
STEPS = (
    Step("osm", "OSM et Wikidata", "osm", None, paid=False),
    Step("source", "Lecture de la source des spots", "spots", tuple(spot_chain.FREE_PARTS), paid=False),
    Step("carburants", "Carburants", "carburants", None, paid=False, needs=OSM_DONE),
    Step("finess", "Pharmacies FINESS", "finess", None, paid=False, needs=OSM_DONE),
    Step("pepites", "Pépites de la ville", "pepites", None, paid=True, needs=OSM_DONE),
    Step("services", "Services", "services", None, paid=True, needs=OSM_DONE),
    Step("agents_spots", "Agents des spots", "spots", tuple(spot_chain.AGENTS), paid=True, needs=SOURCE_DONE),
)
STEPS_BY_KEY = {step.key: step for step in STEPS}

# Ce que la supervision lit quand une ville attend l'étape d'avant.
NEEDS_LABELS = {OSM_DONE: "OSM et Wikidata", SOURCE_DONE: "la lecture de la source des spots"}


def owns(step: Step, chain: str, part: str) -> bool:
    """Cette partie de cette chaîne est-elle faite par cette étape ?"""
    return step.chain == chain and (step.parts is None or part in step.parts)


def step_for(chain: str, part: str) -> Step | None:
    """
    L'étape qui fait cette partie de cette chaîne. Pour un passage en file, on la demande pour sa prochaine partie à
    faire : c'est l'étape qui doit le prendre. None pour une chaîne qu'aucune étape ne connaît.
    """
    return next((step for step in STEPS if owns(step, chain, part)), None)


def cities_to_check(step: Step, passage: dict) -> list:
    """
    Les villes dont l'étape d'avant doit être finie. Les services cherchent une commune : on regarde l'OSM de toutes
    ses villes (une rando partie de Lochrist a chargé l'OSM de Lochrist, les services cherchent Le Conquet). Les autres
    étapes travaillent sur la ville elle-même.
    """
    if step.chain != "services":
        return [passage["city_id"]]
    cities = service_store.load_cities()
    city = next((row for row in cities if row["id"] == passage["city_id"]), None)
    if city is None:
        return [passage["city_id"]]
    return [row["id"] for row in cities if service_store.commune_key(row) == service_store.commune_key(city)]


def missing_need(step: Step, passage: dict) -> str | None:
    """
    Ce que la ville attend avant cette étape, en phrase lisible ; None si elle est prête.
    Une ville attend tant que l'étape d'avant est demandée pour elle sans être finie (en file, en cours, ou en échec
    pas encore repris). Une ville où elle a été finie une fois est prête ; une ville où elle n'a jamais été demandée
    aussi (une ville ajoutée avant les passages) : rien ne viendra, il ne faut pas l'attendre.
    """
    if step.needs is None:
        return None
    chain, part = step.needs
    city_ids = cities_to_check(step, passage)
    if part in passage_store.finished_parts(chain, city_ids):
        return None
    if not passage_store.pending_part(chain, part, city_ids, passage["passage_id"]):
        return None
    return f"attend {NEEDS_LABELS[step.needs]} de la ville"
