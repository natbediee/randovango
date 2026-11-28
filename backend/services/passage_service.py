"""
Lancer une chaîne d'agents sur une ville, la faire tourner en fond et dire où elle en est (issue #204).

UN PASSAGE EN TROIS TEMPS
    1. create_passage écrit la demande : la chaîne, la ville, les catégories, l'origine. Le passage est « en file ».
    2. run_passage le fait tourner, en tâche de fond : il prend le verrou de la chaîne, puis passe les catégories l'une
       après l'autre, en notant l'état de chacune (en cours, fini, échec, et la raison d'un échec).
    3. read_passage assemble ce que la supervision affiche : la trace (passage_store) et, pour le coût et l'étape de
       chaque catégorie, les appels d'agents lus dans llm_calls sous le même identifiant.
La route de la supervision fait 1 puis 2 (api/routers/supervision_passages.py). Le lancement à la fin de l'ETL d'une
nouvelle ville (#211) appellera les mêmes fonctions, avec l'origine « etl ».

UNE VRAIE MISE À JOUR, TOUJOURS
Un passage lancé ici enregistre ce qu'il trouve. L'essai (rien en base) et le rejeu des règles restent des outils de la
ligne de commande, pour la développeuse (python -m agents.find_services --essai, --rejouer).

LA CHAÎNE EST UN PARAMÈTRE
CHAINS donne, pour chaque chaîne, ses catégories, son verrou et la façon de faire passer une catégorie. Y sont branchées
la chaîne des services (payante) et, depuis #276, les chaînes gratuites de l'ajout d'une ville : OSM, pharmacies FINESS,
carburants (services/etl_chains.py), la chaîne des spots (services/spot_chain.py), payante sauf sa source, et celle
des pépites d'une ville (services/pepite_chain.py), payante. Toujours sans nouvelle route.

REPRENDRE SANS REPAYER
Un passage en échec garde ce qui est fini. resume_passage en crée un nouveau, qui ne refait que les catégories non
finies ; une grande ville cherchée par zones reprend en plus les zones finies de son fichier (service_chain).
Le passage en échec reste tel quel, trace fidèle de ce qui s'est passé : la reprise le désigne (resumed_from), et lui
connaît sa reprise (repris_par). Un passage ne se reprend qu'une fois : si la reprise échoue, c'est elle qu'on reprend.

LES HEURES, À L'HEURE DE PARIS (#299)
Les heures des passages sont gardées en UTC dans la base ; read_passage et le message d'un passage qui tourne déjà les
rendent à l'heure de Paris, avec leur fuseau (utils/paris_time.py). Le code qui décide (la file, les reprises) compare
toujours les heures de la base entre elles, en UTC.
"""
import re
from dataclasses import dataclass
from typing import Callable

from agents import find_services
from agents.find_services import PassageRunning
from agents.llm_service import LLMLimitReached, LLMRefused, LLMTimeout, mesure_passage, new_passage_id
from agents.service_chain import RegisterUnavailable, interrupted_trace, latest_traces
from services import (agents_pause, budget_service, etl_chains, llm_calls_service, passage_steps, passage_store,
                      pepite_chain, service_store, spot_chain)
from services.etl_chains import StepFailed
from services.spot_chain import SpotsMissed
from services.passage_store import DONE, FAILED, QUEUED, RESUMED, RUNNING, TO_DO, WAITING
from utils.geo_utils import city_commune
from utils.paris_time import to_paris
from utils.logger_util import LoggerUtil

logger = LoggerUtil.get_logger("passages")

# Qui a demandé le passage : l'administratrice depuis la supervision ; une rando envoyée par un compte admin depuis la
# page d'ajout (#356) ; ou l'ETL d'une nouvelle ville (#211), pour un envoi en masse ou un compte contributeur.
# Les deux premières passent devant l'ETL dans leur étape (passage_store.PRIORITY_ORIGINS).
ORIGINS = ("supervision", "ajout", "etl")
SAVING = "enregistrement"            # l'étape de l'enregistrement, que le code note lui-même : elle n'appelle aucun agent
PAUSED = "budget"                    # l'étape d'une catégorie arrêtée en route par le budget : elle reprendra son fichier
LOADING = "chargement"               # l'étape d'une partie d'une chaîne sans agent (OSM, FINESS, carburants) qui tourne


class PassageConflict(RuntimeError):
    """Le passage ne peut pas partir maintenant : un autre tourne, ou il n'y a rien à reprendre. Le message le dit."""


class BudgetReached(RuntimeError):
    """Le budget des agents est atteint pendant un passage : il s'arrête avant la prochaine catégorie ou zone (#211)."""


@dataclass(frozen=True)
class Chain:
    """Une chaîne d'agents qu'on peut lancer sur une ville."""
    key: str
    label: str
    parts: dict                 # {clé de la catégorie : son libellé}, dans l'ordre où elles passent
    paid: bool                  # payante (des agents) ou gratuite (OSM, fichiers de l'État)
    # (id de la ville, partie) -> le verrou « un seul passage à la fois » : un bloc « with ». La partie est la première
    # que le passage va faire : la chaîne des spots a un verrou pour sa source et un autre pour ses agents (#332).
    lock: Callable
    lock_is_free: Callable      # (id de la ville, partie) -> le verrou est-il libre ?
    run_part: Callable          # (passage_id, clé, ville, reprise, vérification du budget) -> le bilan de la catégorie
    steps_of: Callable          # (clé) -> {agent : l'étape qu'il fait}, pour lire l'étape dans llm_calls
    # False : un seul passage à la fois, toutes villes confondues (services, spots). True : un passage à la fois par
    # ville (les chaînes gratuites de l'ETL : deux villes ajoutées coup sur coup gardent leur OSM en même temps).
    per_city: bool = False
    # True : la chaîne travaille sur la commune de la ville, depuis une seule de ses villes (Morgat se cherche comme
    # Crozon : la chaîne des services). False : sur la ville elle-même (l'OSM et les spots de Morgat sont les siens).
    searches_commune: bool = False
    # Les parties gratuites d'une chaîne payante : le budget des agents ne les retient pas (la source des spots).
    free_parts: tuple = ()


# --- La chaîne des services ---

SERVICE_CATEGORIES = {category.key: category for category in find_services.CATEGORIES}
SERVICE_LABELS = {"restaurants": "Recherche des restaurants", "commerces": "Recherche des commerces",
                  "supermarches": "Recherche des supermarchés", "laveries": "Recherche des laveries"}


def run_service_category(passage_id: str, key: str, city: dict, resume: bool, check_budget) -> dict:
    """
    Une catégorie de la chaîne des services : ses trois agents cherchent, analysent et prouvent, puis le code enregistre.
    En reprise, le fichier d'un passage arrêté en route est repris : ses zones finies ne sont pas repayées.
    `check_budget` arrête la recherche d'une grande ville entre deux zones quand le budget est atteint.
    """
    category = SERVICE_CATEGORIES[key]
    stopped = interrupted_trace(category, city) if resume else None
    return find_services.search_and_save(
        category, city, stopped=stopped,
        before_saving=lambda: passage_store.set_part(passage_id, key, RUNNING, step=SAVING), check_budget=check_budget)


def service_steps(key: str) -> dict:
    """Les trois agents d'une catégorie (service_category.py) et l'étape que fait chacun."""
    return {f"find_{key}": "recherches", f"analyze_{key}": "analyse", f"prove_{key}": "preuves"}


# --- Les chaînes gratuites de l'ajout d'une ville (services/etl_chains.py) ---

def free_chain(key: str, label: str, part_label: str, run_part: Callable) -> Chain:
    """Une chaîne gratuite, sans agent, d'une seule partie, avec un verrou par ville."""
    return Chain(key=key, label=label, parts={key: part_label}, paid=False,
                 lock=lambda city_id, part: etl_chains.city_lock(key, city_id),
                 lock_is_free=lambda city_id, part: etl_chains.city_lock_is_free(key, city_id),
                 run_part=run_part, steps_of=lambda part: {}, per_city=True)


CHAINS = {
    # La chaîne des services ne regarde pas la ville pour son verrou : un seul passage à la fois, partout.
    "services": Chain(key="services", label="Recherche des services", parts=SERVICE_LABELS, paid=True,
                      lock=lambda city_id, part: find_services.single_passage(),
                      lock_is_free=lambda city_id, part: find_services.lock_is_free(),
                      run_part=run_service_category, steps_of=service_steps, searches_commune=True),
    # La chaîne des spots (services/spot_chain.py) : la source, gratuite, puis trois agents payants.
    "spots": Chain(key="spots", label="Chaîne des spots", parts=spot_chain.PARTS, paid=True,
                   lock=spot_chain.lock, lock_is_free=spot_chain.lock_is_free, run_part=spot_chain.run_part,
                   steps_of=spot_chain.steps_of, free_parts=spot_chain.FREE_PARTS),
    # La chaîne des pépites d'une ville (services/pepite_chain.py) : payante, comptée comme une chaîne dans le budget.
    "pepites": Chain(key="pepites", label="Pépites de la ville", parts=pepite_chain.PARTS, paid=True,
                     lock=lambda city_id, part: etl_chains.city_lock("pepites", city_id),
                     lock_is_free=lambda city_id, part: etl_chains.city_lock_is_free("pepites", city_id),
                     run_part=pepite_chain.run_part, steps_of=pepite_chain.steps_of, per_city=True),
    "osm": free_chain("osm", "Lieux d'OpenStreetMap", "Lieux d'OpenStreetMap", etl_chains.run_osm),
    "finess": free_chain("finess", "Pharmacies du registre FINESS", "Pharmacies du registre FINESS",
                         etl_chains.run_finess),
    "carburants": free_chain("carburants", "Stations-service et carburants", "Stations-service et prix des carburants",
                             etl_chains.run_fuel),
}


# --- Une chaîne que ce code ne connaît pas ---
# La base est commune à toutes les branches : un passage peut y avoir été écrit par une version plus récente du code,
# avec une chaîne que celle-ci ne connaît pas encore (une branche qui n'a pas ramené main). Il est montré tel quel, sans
# faire planter la supervision ; il n'est ni lancé, ni repris, ni marqué interrompu par cette version.
UNKNOWN_CHAIN = "chaîne inconnue de cette version du code : à suivre et relancer depuis main à jour"


def unknown_chain(key: str) -> Chain:
    """
    Une chaîne de remplacement, pour lire un passage d'une chaîne inconnue. Son verrou se dit toujours pris : ainsi
    personne ici ne croit le passage interrompu (il tourne peut-être sous une autre version), et la file ne le prend pas.
    """
    def refuse(city_id, part):
        raise PassageConflict(UNKNOWN_CHAIN)
    return Chain(key=key, label=key, parts={}, paid=True, lock=refuse, lock_is_free=lambda city_id, part: False,
                 run_part=None, steps_of=lambda part: {})


def chain_of(key: str) -> Chain:
    """La chaîne de cette clé, ou une chaîne de remplacement si ce code ne la connaît pas."""
    return CHAINS.get(key) or unknown_chain(key)


# --- La raison d'un échec, en phrase lisible ---

# Trois façons de manquer de Claude, qui ne se règlent pas de la même façon : la raison dit quoi faire et quand.
# 1. Le quota de l'abonnement (moteur claude-code) revient seul, à l'heure qu'il donne :
#    « You've hit your session limit · resets 1:40pm (UTC) » (journal des agents, 9 octobre 2026).
SUBSCRIPTION_QUOTA = re.compile(r"hit your .*limit|usage limit", re.IGNORECASE)
QUOTA_RESET = re.compile(r"resets (\S+(?: \([A-Z]+\))?)", re.IGNORECASE)    # « 1:40pm (UTC) »
# 2. Le crédit prépayé de l'API est vide (erreur 400 « Your credit balance is too low ») : il ne revient jamais seul,
#    il faut recharger le compte. Une relance automatique (#211) ne doit donc pas le reprendre.
API_CREDIT = re.compile(r"credit balance", re.IGNORECASE)
# 3. Trop d'appels à la minute (erreur 429, rate_limit_error) ou API surchargée (erreur 529, overloaded_error) :
#    revient en quelques minutes. Le module anthropic a déjà réessayé deux fois avant d'abandonner.
# Depuis #332, le quota et « trop d'appels » arrivent en LLMLimitReached : une partie payante ainsi coupée attend en
# file (services/agents_pause.py) au lieu d'échouer. Ces raisons ne se lisent plus que pour une coupure hors d'une
# partie payante, ou dans les échecs d'avant.
API_BUSY = re.compile(r"rate.?limit|overloaded|Error code: (429|529)", re.IGNORECASE)
REASON_LENGTH = 255         # la longueur des colonnes error


def failure_reason(error: Exception) -> str:
    """
    La raison d'un échec, telle que l'administratrice la lit. Les cas connus sont traduits ; un cas inconnu garde le
    message d'origine, pour qu'on puisse le chercher dans les journaux.
    """
    message = str(error)
    if isinstance(error, SpotsMissed):
        # Une partie de la chaîne des spots finie avec des ratés : combien, et pourquoi le dernier a raté.
        cause = failure_reason(error.cause) if error.cause else "raison inconnue"
        reason = (f"{error.missed} spot{'s' if error.missed > 1 else ''} raté{'s' if error.missed > 1 else ''} sur "
                  f"{error.missed + error.done} ({cause}) : reprendre, les spots faits ne seront pas repayés")
    elif isinstance(error, StepFailed):
        reason = message        # déjà écrite pour l'administratrice (services/etl_chains.py)
    elif isinstance(error, PassageRunning):
        reason = "un autre passage tournait déjà : relancer après sa fin"
    elif isinstance(error, RegisterUnavailable):
        reason = "registre des entreprises illisible : une grande ville n'est pas cherchée sans lui, relancer plus tard"
    elif SUBSCRIPTION_QUOTA.search(message):
        reset = QUOTA_RESET.search(message)
        when = f"il revient à {reset.group(1)} : reprendre après cette heure" if reset else "reprendre plus tard"
        reason = f"quota de l'abonnement Claude atteint ({when}), les catégories finies ne seront pas repayées"
    elif API_CREDIT.search(message):
        reason = "crédit de l'API Anthropic épuisé : recharger le compte, puis reprendre"
    elif API_BUSY.search(message):
        reason = "trop d'appels à Claude en même temps : reprendre dans quelques minutes"
    elif isinstance(error, LLMTimeout):
        reason = "délai dépassé : Claude n'a pas répondu à temps"
    elif isinstance(error, LLMRefused):
        reason = "Claude a refusé de répondre"
    else:
        reason = f"erreur : {message}"
    return reason[:REASON_LENGTH]


# --- Lancer ---

def find_city(city_id: int) -> dict | None:
    """La ville de l'appli (table cities), avec sa commune officielle ; None si elle n'existe pas."""
    return next((city for city in service_store.load_cities() if city["id"] == city_id), None)


def check_not_open(chain: Chain, city_id: int) -> None:
    """
    Lève PassageConflict, avec un message qui le nomme, si un passage de cette chaîne est déjà en file, en attente ou
    en cours sur cette ville : le lancer une seconde fois referait (ou repaierait) le même travail.
    Un passage de la même chaîne sur une autre ville ne retient plus rien (#332) : le nouveau entre dans la file de
    son étape et part à son tour.
    """
    active = [passage_store.load_passage(passage_id) for passage_id in passage_store.active_ids(chain.key, city_id)]
    passage = next((passage for passage in active if passage), None)
    if passage is None:
        return
    if passage["status"] == RUNNING:
        raise PassageConflict(f"Un passage « {chain.label} » tourne déjà sur {passage['city_name']}, depuis le "
                              f"{to_paris(passage['started_at']):%d/%m/%Y à %H h %M} : attendre sa fin avant d'en lancer un autre.")
    raise PassageConflict(f"Un passage « {chain.label} » est déjà demandé sur {passage['city_name']} "
                          f"({passage['passage_id']}, {passage['status']}) : il partira à son tour.")


def part_is_paid(chain: Chain, part: str) -> bool:
    """Une partie est payante si sa chaîne l'est et qu'elle n'en est pas une partie gratuite (la source des spots)."""
    return chain.paid and part not in chain.free_parts


def check_budget(chain: Chain, parts: list) -> None:
    """
    Lève PassageConflict, avec la raison, si le budget des agents est atteint (issue #211) : un passage payant ne part
    pas, même lancé à la main, tant que le budget ne le permet pas de nouveau ou que l'admin ne le relève pas.
    Un passage sans partie payante (OSM, fichiers de l'État, la seule source des spots) n'est jamais retenu.
    """
    if not any(part_is_paid(chain, part) for part in parts):
        return
    reason = budget_service.budget_block()
    if reason:
        raise PassageConflict(f"Budget des agents atteint ({reason}).")


def stop_if_over_budget(chain: Chain, part: str) -> None:
    """
    Pendant un passage, avant chaque catégorie et chaque zone d'une grande ville (ou chaque spot) : lève BudgetReached
    si le budget des agents est atteint. Le budget n'est donc jamais dépassé de plus d'une zone ou d'un spot.
    Une partie gratuite n'est jamais arrêtée.
    """
    if not part_is_paid(chain, part):
        return
    reason = budget_service.budget_block()
    if reason:
        raise BudgetReached(reason)


def create_passage(chain_key: str, city_id: int, parts: list | None = None, origin: str = "supervision",
                   resumed_from: str | None = None, status: str = QUEUED) -> str:
    """
    Écrit un passage demandé, en file, et renvoie son identifiant. Sans catégories, toutes celles de la chaîne.
    Lève ValueError pour une chaîne, une ville, une catégorie ou une origine inconnue.
    Lancé depuis la supervision, il est refusé (PassageConflict) si la même chaîne est déjà demandée sur la ville ou si
    le budget des agents est atteint : l'admin le sait tout de suite. Une reprise (resumed_from) n'est refusée que pour
    le budget : la ligne des reprises dit déjà qu'il n'y en a qu'une à la fois (#332). Demandé par l'ETL, il n'est
    jamais refusé : il prend sa place dans la file de son étape, qui le lance à son tour (passage_queue.py).
    `status` : WAITING pour un passage de l'ETL quand la mise à jour automatique est coupée ; il attend l'admin.
    Le faire tourner : run_passage.
    """
    chain = CHAINS.get(chain_key)
    if chain is None:
        raise ValueError(f"Chaîne inconnue : {chain_key} (attendu : {', '.join(CHAINS)})")
    unknown = [part for part in parts or () if part not in chain.parts]
    if unknown:
        raise ValueError(f"Catégorie inconnue : {', '.join(unknown)} (attendu : {', '.join(chain.parts)})")
    if origin not in ORIGINS:
        raise ValueError(f"Origine inconnue : {origin} (attendu : {', '.join(ORIGINS)})")
    if find_city(city_id) is None:
        raise ValueError(f"Ville inconnue : {city_id}")
    # Les catégories passent toujours dans l'ordre de la chaîne : la suivante trouve en base ce que la précédente a écrit.
    chosen = [part for part in chain.parts if not parts or part in parts]
    if origin == "supervision":
        if resumed_from is None:
            check_not_open(chain, city_id)
        check_budget(chain, chosen)
    passage_id = new_passage_id()
    passage_store.insert_passage(passage_id, chain_key, city_id, origin, chosen, resumed_from, status)
    logger.info(f"[passages] {passage_id} demandé ({status}) : {chain_key}, ville {city_id}, {chosen}, origine {origin}")
    return passage_id


def city_to_run(chain: Chain, passage: dict) -> dict:
    """
    La ville sur laquelle la chaîne travaille. La chaîne des services cherche une commune depuis une seule de ses
    villes : Morgat se cherche comme Crozon. Les autres chaînes travaillent sur la ville elle-même : l'OSM de Morgat
    et ses spots sont les siens.
    """
    if chain.searches_commune:
        return service_store.load_city(passage["city_name"])
    return {"id": passage["city_id"], "name": passage["city_name"]}


def parts_to_run(passage_id: str, parts: list | None) -> list:
    """
    Les parties à faire que ce passage fait tourner maintenant, dans l'ordre : toutes, ou seulement celles de `parts`
    (les parties de l'étape de la file qui le prend : la source des spots seule, puis ses trois agents).
    """
    rows = [row for row in passage_store.load_parts(passage_id) if row["status"] == TO_DO]
    return [row for row in rows if parts is None or row["part"] in parts]


def agents_limit(error: Exception) -> LLMLimitReached | None:
    """
    La limite passagère du fournisseur des agents (quota, trop d'appels) qui a coupé la partie : l'erreur elle-même,
    ou, pour des spots ratés, la cause du dernier raté ; None pour toute autre erreur.
    """
    cause = error.cause if isinstance(error, SpotsMissed) else error
    return cause if isinstance(cause, LLMLimitReached) else None


def run_passage(passage_id: str, parts: list | None = None) -> None:
    """
    Fait tourner un passage en file, partie après partie, sous le verrou de sa chaîne. Ne lève jamais : c'est une
    tâche de fond, personne n'attend sa réponse. Un échec est écrit dans la trace, avec sa raison ; les parties
    finies avant lui restent enregistrées, et celles d'après restent « à faire », pour la reprise.
    `parts` : les seules parties à faire maintenant (l'étape de la file, #332) ; s'il en reste d'autres après elles, le
    passage retourne en file, et l'étape suivante le prendra (les agents des spots après la source).
    Si le verrou est pris, le passage reste en file, sans échec : la file le relancera plus tard (#211).
    Sous le verrou de sa chaîne, le passage tient aussi le verrou à son nom (passage_lock, #352) : c'est lui qui dit
    qu'il tourne vraiment. Le travail et l'état final du passage s'écrivent sous ces verrous (run_parts) : la file
    regarde chaque minute les passages « en cours » sans verrou pour les dire coupés (#344), et un passage qui vient
    de finir ne doit jamais être vu ainsi entre la fin de son verrou et l'écriture de son état.
    """
    passage = passage_store.load_passage(passage_id)
    if passage["chain"] not in CHAINS:
        logger.warning(f"[passages] {passage_id} laissé tel quel : {UNKNOWN_CHAIN}")
        return
    chain = CHAINS[passage["chain"]]
    first = parts_to_run(passage_id, parts)
    if not first:
        return
    try:
        city = city_to_run(chain, passage)
        with chain.lock(passage["city_id"], first[0]["part"]), passage_lock(passage_id), mesure_passage(passage_id):
            # Relu sous le verrou : deux fils peuvent viser le même passage ; le second à prendre le verrou le trouve
            # déjà parti et ne le refait pas.
            if passage_store.load_passage(passage_id)["status"] != QUEUED:
                return
            passage_store.set_passage_status(passage_id, RUNNING)
            run_parts(passage_id, chain, city, passage["resumed_from"] is not None, parts)
    except PassageRunning:
        # Le verrou était pris avant que le passage commence : il garde sa place dans la file.
        logger.info(f"[passages] {passage_id} attend : un autre passage tient le verrou")
    except Exception as error:
        # Une erreur avant la première partie (ville introuvable, base injoignable au moment du verrou).
        reason = failure_reason(error)
        logger.exception(f"[passages] {passage_id} en échec (avant la première catégorie) : {reason}")
        passage_store.set_passage_status(passage_id, FAILED, reason)


def run_parts(passage_id: str, chain: Chain, city: dict, resume: bool, parts: list | None) -> None:
    """
    Les parties à faire du passage, l'une après l'autre, puis son état final : fini, en file pour l'étape suivante,
    en file pour attendre (budget, limite du fournisseur des agents), ou en échec. Appelé sous le verrou de la chaîne.
    Si le budget est atteint, ou si le fournisseur des agents refuse pour un temps, le passage s'arrête avant la partie
    ou la zone suivante et retourne en file : ce qui est fini reste enregistré, et la file le reprend là où il en
    était (#332).
    """
    part = None
    try:
        for row in parts_to_run(passage_id, parts):
            part = row["part"]
            stop_if_over_budget(chain, part)
            passage_store.set_part(passage_id, part, RUNNING)
            # Une partie arrêtée par le budget ou le quota reprend son fichier : rien de fait n'est repayé.
            summary = chain.run_part(passage_id, part, city, resume or row["step"] == PAUSED,
                                     lambda: stop_if_over_budget(chain, part))
            passage_store.set_part(passage_id, part, DONE, summary=summary)
        if parts_to_run(passage_id, None):
            passage_store.set_passage_status(passage_id, QUEUED)
            logger.info(f"[passages] {passage_id} : étape finie, le passage attend l'étape suivante")
        else:
            passage_store.set_passage_status(passage_id, DONE)
            logger.info(f"[passages] {passage_id} fini")
    except BudgetReached as reason:
        # Pas un échec : le passage retourne en file, et la partie arrêtée garde l'étape « budget » pour la reprise.
        logger.info(f"[passages] {passage_id} arrêté avant {part} : {reason}")
        pause_part(passage_id, part)
    except Exception as error:
        limit = agents_limit(error) if part and part_is_paid(chain, part) else None
        if limit:
            # Une limite passagère, pas une panne : le passage attend en file l'heure de retour, sans échec (#332).
            agents_pause.pause(limit.until, limit.reason)
            logger.info(f"[passages] {passage_id} arrêté pendant {part} : {limit.reason}, jusqu'à {limit.until:%H:%M}")
            pause_part(passage_id, part)
            return
        reason = failure_reason(error)
        logger.exception(f"[passages] {passage_id} en échec ({part or 'avant la première catégorie'}) : {reason}")
        if part:
            passage_store.set_part(passage_id, part, FAILED, error=reason)
        passage_store.set_passage_status(passage_id, FAILED, reason)


def pause_part(passage_id: str, part: str) -> None:
    """La partie arrêtée garde l'étape « budget », pour reprendre son fichier, et le passage retourne en file."""
    passage_store.set_part(passage_id, part, TO_DO, step=PAUSED)
    passage_store.set_passage_status(passage_id, QUEUED)


def searched_service_categories(cities: list) -> set:
    """
    Les catégories de services déjà cherchées jusqu'au bout pour une commune (ses villes : `cities`), d'après les
    fichiers des passages des agents. Les fichiers, et pas la table passages : les communes cherchées en ligne de
    commande, avant la supervision, n'ont aucune ligne dans passages. Un fichier porte le nom de la commune, ou celui de
    la ville pour un passage d'avant le 8 novembre 2026 (Morgat pour Crozon) : les deux sont regardés.
    """
    names = {city_commune(city) for city in cities} | {city["name"] for city in cities}
    return {key for key, category in SERVICE_CATEGORIES.items() if names & set(latest_traces(category))}


def request_etl_passage(city_name: str, origin: str = "etl") -> str | None:
    """
    À la fin de l'ETL d'une ville : demande le passage de la chaîne des services pour sa commune, et rend son
    identifiant ; None s'il n'y a rien à chercher.
    1. Le nom de l'ETL est converti en commune officielle (code INSEE) : une rando partie de Lochrist fait chercher
       Le Conquet, depuis la ville qui porte le nom de la commune.
    2. Seules les catégories jamais cherchées pour cette commune, et pas déjà demandées, sont demandées : une seconde
       rando dans une commune déjà faite ne coûte rien. « Déjà cherchée » se lit à deux endroits : les fichiers des
       passages (les communes cherchées en ligne de commande n'ont rien dans la base) et les parties finies de la base
       (commune à toutes les branches, quand les fichiers ne le sont pas).
    3. Le passage entre dans la file ; si la mise à jour automatique est coupée, il attend l'admin (« en attente »).
    `origin` : « ajout » pour une rando envoyée par un compte admin depuis la page d'ajout, qui passe devant (#356).
    """
    city = service_store.load_city(city_name)
    if city is None:
        logger.warning(f"[passages] {city_name} : ville inconnue, aucun passage des services demandé")
        return None
    commune = [other for other in service_store.load_cities()
               if service_store.commune_key(other) == service_store.commune_key(city)]
    city_ids = [c["id"] for c in commune]
    already = (searched_service_categories(commune) | passage_store.finished_parts("services", city_ids)
               | passage_store.open_parts("services", city_ids))
    left = [key for key in SERVICE_LABELS if key not in already]
    if not left:
        logger.info(f"[passages] {city_name} : {city_commune(city)} déjà cherchée, aucun passage des services demandé")
        return None
    status = QUEUED if budget_service.load_settings()["services_after_etl"] else WAITING
    return create_passage("services", city["id"], left, origin=origin, status=status)


def parts_already_asked(chain_key: str, city_id: int) -> set:
    """
    Les parties d'une chaîne que l'ETL ne redemande pas sur cette ville : déjà finies, ou déjà demandées (en file, en
    attente, en cours, ou en échec pas encore repris). La source des spots compte aussi comme faite quand histo_scrap
    dit la ville déjà lue (une ville lue avant les passages).
    """
    already = passage_store.finished_parts(chain_key, [city_id]) | passage_store.open_parts(chain_key, [city_id])
    if chain_key == "spots" and spot_chain.source_already_read(city_id):
        already.add("source")
    return already


def request_city_chain(chain_key: str, city_name: str, origin: str = "etl") -> str | None:
    """
    À l'arrivée d'une rando : met dans la file une chaîne de l'ajout d'une ville (OSM, carburants, FINESS, spots,
    pépites) sur sa ville, et rend l'identifiant du passage ; None si la chaîne n'a plus rien à faire sur la ville.
    Seules les parties jamais finies et pas déjà demandées sont demandées (issue #316) : cinq randos envoyées ensemble à
    l'Île-d'Yeu avaient lancé cinq OSM et trois FINESS (23 novembre 2026). Une ville déjà faite n'est donc plus relancée
    par une nouvelle rando ; l'admin peut toujours la relancer depuis la supervision.
    Ces chaînes travaillent sur la ville elle-même, pas sur sa commune : l'OSM de Morgat est le sien.
    `origin` : « ajout » pour une rando envoyée par un compte admin depuis la page d'ajout, qui passe devant (#356).
    """
    city = next((row for row in service_store.load_cities() if row["name"] == city_name), None)
    if city is None:
        logger.warning(f"[passages] {city_name} : ville inconnue, chaîne {chain_key} non demandée")
        return None
    already = parts_already_asked(chain_key, city["id"])
    left = [part for part in CHAINS[chain_key].parts if part not in already]
    if not left:
        logger.info(f"[passages] {city_name} : chaîne {chain_key} déjà faite ou déjà demandée, rien de plus")
        return None
    return create_passage(chain_key, city["id"], left, origin=origin)


def launch_waiting(passage: dict) -> str:
    """
    Lance une ville que l'ETL a laissée en attente (mise à jour automatique coupée) : le passage est remis en file,
    à sa place, et part au tour de son étape. Seul le budget atteint le refuse : un passage de la même chaîne qui
    tourne sur une autre ville ne le retient plus (#332).
    """
    chain = CHAINS[passage["chaine"]]
    check_budget(chain, [part["cle"] for part in passage["categories"] if part["etat"] != DONE])
    passage_store.set_passage_status(passage["passage_id"], QUEUED)
    logger.info(f"[passages] {passage['passage_id']} lancé par l'admin après l'attente")
    return passage["passage_id"]


def resume_passage(passage_id: str, origin: str = "supervision") -> str | None:
    """
    La relance d'une ville non faite, par l'admin, et l'identifiant du passage à faire tourner :
    - un passage en échec est repris par un nouveau passage, qui ne refait que ses catégories non finies ;
    - un passage en attente (mise à jour automatique coupée, #211) part lui-même, sans nouveau passage.
    None si le passage n'existe pas ; PassageConflict s'il n'est ni en échec ni en attente, s'il a déjà été repris, ou
    si le budget est atteint. Un passage de la même chaîne qui tourne sur une autre ville ne retient plus la reprise :
    elle entre dans la file et part à son tour (#332 : la reprise des spots de Bedous était refusée, « tourne déjà sur
    Rocquefort »).
    """
    passage = read_passage(passage_id)
    if passage is None:
        return None
    if passage["chaine"] not in CHAINS:
        raise PassageConflict(f"Ce passage ne se relance pas ici : {UNKNOWN_CHAIN}.")
    if passage["etat"] == WAITING:
        return launch_waiting(passage)
    if passage["etat"] != FAILED:
        raise PassageConflict(f"Ce passage est « {passage['etat']} » : seul un passage en échec ou en attente se relance.")
    # Une reprise à la fois : les reprises forment une seule ligne (aaa, puis bbb qui reprend aaa, puis ccc qui reprend
    # bbb). L'écran sait ainsi qu'un échec déjà repris n'attend plus rien : sa reprise dit où en est la ville.
    if passage["repris_par"]:
        raise PassageConflict(f"Ce passage a déjà été repris par {passage['repris_par']} : reprendre celui-là s'il a échoué.")
    left = [part["cle"] for part in passage["categories"] if part["etat"] != DONE]
    resumed = create_passage(passage["chaine"], passage["ville"]["id"], left, origin, resumed_from=passage_id)
    # Les parties jamais commencées de l'échec passent à « reprise » : c'est la reprise qui les fait (#295).
    passage_store.close_resumed_parts()
    return resumed


# --- Dire où il en est ---

def list_chains() -> list:
    """
    Les chaînes qu'on peut lancer, dans l'ordre de CHAINS : leur clé (à envoyer dans « chaine »), leur libellé, si elles
    sont payantes (des agents, retenues par le budget) ou gratuites, et leurs parties (à envoyer dans « categories »).
    """
    return [{"chaine": chain.key, "libelle": chain.label, "payant": chain.paid,
             "categories": [{"cle": key, "libelle": label, "payant": part_is_paid(chain, key)}
                            for key, label in chain.parts.items()]}
            for chain in CHAINS.values()]


AUTO_OFF = "mise à jour automatique coupée : à lancer depuis la supervision"
CUT_LIMIT = 200     # les passages « en cours » regardés à chaque tour : bien plus que les huit fils de la file


def paid_wait() -> str | None:
    """Pourquoi les parties payantes attendent : la limite du fournisseur des agents d'abord (#332), puis le budget."""
    return agents_pause.paused_reason() or budget_service.budget_block()


def waiting_reason(passage: dict) -> str | None:
    """
    Pourquoi un passage n'a pas encore tourné, en phrase lisible ; None s'il tourne, a fini, ou peut partir.
    En file : l'étape d'avant pas finie pour la ville (#332), puis le verrou, puis la limite des agents et le budget.
    """
    if passage["status"] == WAITING:
        return AUTO_OFF
    if passage["status"] != QUEUED:
        return None
    if passage["chain"] not in CHAINS:
        return UNKNOWN_CHAIN
    chain = CHAINS[passage["chain"]]
    to_do = [row["part"] for row in passage_store.load_parts(passage["passage_id"]) if row["status"] == TO_DO]
    if not to_do:
        return None
    step = passage_steps.step_for(chain.key, to_do[0])
    need = passage_steps.missing_need(step, passage) if step else None
    if need:
        return need
    if not chain.lock_is_free(passage["city_id"], to_do[0]):
        return "attend la fin du passage en cours"
    # Seule une prochaine partie payante attend les agents et le budget : la source des spots part quand même.
    return paid_wait() if part_is_paid(chain, to_do[0]) else None


PASSAGE_LOCK = "randovango_passage_{}"     # le verrou d'un passage qui tourne, à son identifiant (#352)


def passage_lock(passage_id: str):
    """
    Le verrou à l'identifiant du passage : un bloc « with », qui lève PassageRunning s'il est déjà tenu. Le passage le
    tient tant qu'il tourne (run_passage). Comme les autres verrous, il appartient à une connexion MySQL : il se libère
    tout seul si le serveur s'arrête en route, ce qui laisse voir le passage coupé.
    """
    return etl_chains.named_lock(PASSAGE_LOCK.format(passage_id), "Ce passage tourne déjà.")


def interrupt_if_cut(passage: dict) -> bool:
    """
    Marque « interrompu » un passage coupé, et dit s'il l'était. Un passage coupé est « en cours » dans la base alors
    que personne ne tient son verrou : le serveur a redémarré, ou le programme qui le faisait tourner a été arrêté.
    On regarde le verrou du passage lui-même, pas celui de sa chaîne : les services, la source des spots et les
    agents des spots ont un seul verrou pour toutes les villes, et tant que Die tenait celui des services, Ercé,
    coupé par un redémarrage, paraissait tourner encore (27 novembre 2026, #352).
    Pour regarder, on prend le verrou du passage sans attendre : s'il est tenu, le passage tourne vraiment, ici ou
    dans un autre programme sur la même base, et on n'y touche pas. S'il est libre, on le garde pendant qu'on relit
    l'état et qu'on écrit l'échec : le passage ne peut ni démarrer ni finir entre les deux.
    """
    if passage["status"] != RUNNING:
        return False
    try:
        with passage_lock(passage["passage_id"]):
            # Relu sous le verrou : le passage a pu finir juste avant qu'on le prenne.
            if passage_store.load_passage(passage["passage_id"])["status"] != RUNNING:
                return False
            mark_interrupted(passage, passage_store.load_parts(passage["passage_id"]))
            return True
    except PassageRunning:
        return False


def mark_cut_passages() -> list:
    """
    Marque « interrompu » les passages coupés (interrupt_if_cut), et rend leurs identifiants. La file le fait
    elle-même, à chaque tour du fil des reprises (#344) : avant, seul l'affichage de la supervision les voyait, et les
    OSM de Val-de-Sos, Charpey, Buzan et Contrazy, restés « en cours » après l'arrêt des scripts de l'ancienne file,
    bloquaient les autres étapes de leur ville jusqu'à ce qu'on l'ouvre (27 novembre 2026).
    Une fois en échec, un passage coupé sur une partie gratuite est repris seul, comme tout échec gratuit.
    """
    cut = []
    for passage_id in passage_store.passage_ids(RUNNING, CUT_LIMIT):
        passage = passage_store.load_passage(passage_id)
        if passage is None or passage["chain"] not in CHAINS:
            continue        # une chaîne inconnue tourne peut-être sous une autre version du code : on n'y touche pas
        if interrupt_if_cut(passage):
            cut.append(passage_id)
    return cut


def mark_interrupted(passage: dict, parts: list) -> None:
    """
    Un passage « en cours » dont plus personne ne tient le verrou a été coupé : le serveur a redémarré pendant qu'il
    tournait, ou le programme qui le faisait tourner a été arrêté. On l'écrit en échec, une fois pour toutes, pour
    qu'il puisse être repris.
    """
    reason = "passage interrompu (le serveur a redémarré pendant qu'il tournait) : à reprendre"
    for part in parts:
        if part["status"] == RUNNING:
            part["status"], part["error"] = FAILED, reason
            passage_store.set_part(passage["passage_id"], part["part"], FAILED, error=reason)
    passage["status"], passage["error"] = FAILED, reason
    passage_store.set_passage_status(passage["passage_id"], FAILED, reason)


def call_totals(calls: list) -> dict:
    """
    Le nombre d'appels, d'appels ratés et le coût d'une liste d'appels de llm_calls : en dollars, en euros TTC estimés
    au taux de la BCE, avec le taux et ce que vaut le coût (llm_calls_service.calls_cost, #275).
    """
    return {"appels": len(calls), "echecs_appels": sum(call["status"] != "reussi" for call in calls),
            **llm_calls_service.calls_cost(calls)}


# Le bilan d'une catégorie (service_store.save_commune), clé par clé, en morceau de phrase : (singulier, pluriel).
# « fiches » est l'ancien nom des services enregistrés, gardé dans le bilan ; la phrase dit « services ».
SUMMARY_WORDS = {
    "a_confirmer": ("à confirmer dans la supervision", "à confirmer dans la supervision"),
    "meme_nom_dans_la_commune": ("même nom ailleurs dans la commune, à relire comme doublon possible",
                                 "mêmes noms ailleurs dans la commune, à relire comme doublons possibles"),
    "doublons_possibles": ("doublon possible à trancher", "doublons possibles à trancher"),
    "deja_restaurant": ("déjà montré comme restaurant", "déjà montrés comme restaurants"),
    "deja_supermarche": ("déjà montré comme supermarché", "déjà montrés comme supermarchés"),
}
# Les lieux écartés, dits ensemble à la fin, avec leur raison.
DISCARDED_WORDS = {"sans_page": "sans preuve", "liquidation": "société liquidée ou fermée"}


# Le bilan des autres chaînes que les services (etl_chains.py, spot_chain.py) : ce qu'elles ont fait, (singulier, pluriel).
LOADED_WORDS = {"lieux": ("lieu chargé", "lieux chargés"),
                "lieux_wikidata": ("lieu de Wikidata chargé", "lieux de Wikidata chargés"),
                "pharmacies": ("pharmacie chargée", "pharmacies chargées"),
                # La chaîne des spots (services/spot_chain.py).
                "spots_lus": ("spot lu", "spots lus"), "harmonises": ("spot harmonisé", "spots harmonisés"),
                "ouvertures_lues": ("ouverture lue", "ouvertures lues"), "verifies": ("spot vérifié", "spots vérifiés"),
                # La chaîne des pépites (services/pepite_chain.py).
                "pepites_trouvees": ("pépite trouvée", "pépites trouvées"),
                "zones_deja_couvertes": ("zone déjà couverte par une recherche récente",
                                         "zones déjà couvertes par une recherche récente"),
                "stations": ("station chargée", "stations chargées")}


def loaded_text(summary: dict) -> str:
    """
    Le bilan d'une partie en une phrase, hors services : « 42 lieux chargés. », « 0 spot vérifié. »
    En français, 0 et 1 prennent le singulier (« 0 spot vérifié », « 1 ouverture lue ») ; le pluriel commence à 2.
    """
    pieces = []
    for key, count in summary.items():
        one, many = LOADED_WORDS.get(key, (key, key))
        pieces.append(f"{count} {one if count <= 1 else many}")
    return " ; ".join(pieces) + "."


def summary_text(summary: dict | None) -> str | None:
    """
    Le bilan d'une catégorie en une phrase, pour l'écran : « 3 services enregistrés ; 1 même nom ailleurs dans la
    commune, à relire comme doublon possible. » Les cases à zéro ne sont pas dites ; une clé inconnue garde son nom,
    pour ne rien perdre. None tant que la catégorie n'a pas été enregistrée.
    """
    if summary is None:
        return None
    if "fiches" not in summary:
        return loaded_text(summary)
    saved = summary.get("fiches", 0)
    pieces = [f"{saved} service{'s' if saved > 1 else ''} enregistré{'s' if saved > 1 else ''}" if saved
              else "Aucun service enregistré"]
    for key, count in summary.items():
        if key == "fiches" or key in DISCARDED_WORDS or not count:
            continue
        one, many = SUMMARY_WORDS.get(key, (key, key))
        pieces.append(f"{count} {one if count == 1 else many}")
    discarded = {DISCARDED_WORDS[key]: summary[key] for key in DISCARDED_WORDS if summary.get(key)}
    if discarded:
        total = sum(discarded.values())
        reasons = ", ".join(f"{count} {reason}" for reason, count in discarded.items())
        pieces.append(f"{total} écarté{'s' if total > 1 else ''} ({reasons})")
    return " ; ".join(pieces) + "."


def part_state(chain: Chain, part: dict, calls: list, resumed_by: str | None = None) -> dict:
    """
    Ce que l'écran montre d'une catégorie : son état, son étape, son coût, son bilan ou la raison de son échec.
    L'étape vient du dernier appel de ses agents (recherches, analyse, preuves), sauf l'enregistrement, noté par le code.
    Une catégorie « reprise » montre le passage qui l'a refaite (refaite_par, #295) : `resumed_by`, la reprise du passage.
    """
    steps = chain.steps_of(part["part"])
    mine = [call for call in calls if call["agent"] in steps]
    last = mine[-1] if mine else None
    if part["status"] in (TO_DO, DONE, RESUMED):
        step, detail = None, None
    elif part["step"]:
        step, detail = part["step"], None
    else:
        # Une chaîne sans agent (OSM, FINESS, carburants) n'a qu'une étape : le chargement.
        step = steps[last["agent"]] if last else ("recherches" if steps else LOADING)
        detail = last["etape"] if last else None
    return {"cle": part["part"], "libelle": chain.parts.get(part["part"], part["part"]), "payant": part_is_paid(chain, part["part"]), "etat": part["status"],
            "etape": step, "detail_etape": detail, "agent": last["agent"] if last and step != SAVING else None,
            **call_totals(mine), "bilan": part["summary"], "bilan_texte": summary_text(part["summary"]),
            "raison_echec": part["error"], "refaite_par": resumed_by if part["status"] == RESUMED else None,
            "debut": to_paris(part["started_at"]), "fin": to_paris(part["finished_at"])}


# --- Ce qu'un passage a trouvé (le journal passage_items, issue #276) ---

def item_state(row: dict) -> dict:
    """Une ligne du journal telle que l'écran la montre : l'objet, son nom, ajouté ou modifié, par quelle partie, quand."""
    return {"objet": row["item_type"], "id": row["item_id"], "nom": row["item_name"], "action": row["action"],
            "partie": row["part"], "le": to_paris(row["written_at"])}


def found_items(passage_id: str, details: bool, item: tuple | None = None) -> dict:
    """
    Les trouvailles d'un passage : leur nombre, et leur liste quand `details` est vrai (la liste d'un passage, ou celle
    filtrée sur un objet). La liste des passages sans filtre ne les détaille pas (« trouvailles » vaut None) : un passage
    d'une grande ville touche des centaines de spots, GET /passages/{passage_id} les donne.
    `item` : (type, id) pour ne garder que ce que le passage a fait sur cet objet.
    """
    if not details:
        return {"nombre_trouvailles": passage_store.count_items(passage_id), "trouvailles": None}
    rows = passage_store.load_items(passage_id, *(item or ()))
    return {"nombre_trouvailles": len(rows), "trouvailles": [item_state(row) for row in rows]}


def untracked_passage(passage_id: str, item: tuple) -> dict:
    """
    Un passage du journal sans ligne dans passages : un lancement en ligne de commande, ou une action d'un voyageur.
    Il a la même forme qu'un autre passage, les champs inconnus à None, avec ses appels et son coût lus dans llm_calls.
    """
    calls = passage_store.load_calls(passage_id)
    return {"passage_id": passage_id, "chaine": None,
            "libelle_chaine": "lancement hors supervision (ligne de commande ou action d'un voyageur)",
            "ville": None, "origine": None, "prioritaire": False, "etat": None, "payant": bool(calls),
            "demande_le": None, "debut": None, "fin": None, "raison_echec": None, "raison_attente": None,
            "reprise_de": None, "repris_par": None, **call_totals(calls), "categories": [],
            **found_items(passage_id, True, item)}


def read_passage(passage_id: str, details: bool = True, item: tuple | None = None) -> dict | None:
    """
    Tout ce que l'espace Agents de la supervision affiche d'un passage ; None s'il n'existe pas. `details` : la liste de
    ses trouvailles (sinon leur nombre seul) ; `item` : (type, id) pour ne garder que ses trouvailles sur cet objet.
    """
    passage = passage_store.load_passage(passage_id)
    if passage is None:
        return None
    chain = chain_of(passage["chain"])
    if passage["chain"] in CHAINS:      # une chaîne inconnue tourne peut-être sous une autre version du code
        interrupt_if_cut(passage)
    parts = passage_store.load_parts(passage_id)
    calls = passage_store.load_calls(passage_id)
    resumed_by = passage_store.resumed_by(passage_id)
    return {"passage_id": passage_id, "chaine": chain.key, "libelle_chaine": chain.label,
            "ville": {"id": passage["city_id"], "nom": passage["city_name"], "commune": passage["city_commune"]},
            "origine": passage["origin"], "prioritaire": passage["origin"] in passage_store.PRIORITY_ORIGINS,
            "etat": passage["status"], "payant": chain.paid,
            "demande_le": to_paris(passage["requested_at"]), "debut": to_paris(passage["started_at"]),
            "fin": to_paris(passage["finished_at"]),
            "raison_echec": passage["error"], "raison_attente": waiting_reason(passage),
            "reprise_de": passage["resumed_from"],
            "repris_par": resumed_by, **call_totals(calls),
            "categories": [part_state(chain, part, calls, resumed_by) for part in parts],
            **found_items(passage_id, details, item)}


def not_done(queued: list, waiting: list, failed: list) -> list:
    """
    Les villes non faites, avec leur raison, pour le tableau « Villes en attente » de l'espace Agents (#211) :
    celles en file (budget atteint, passage en cours), celles en attente de l'admin (mise à jour coupée), et celles en
    échec que personne n'a encore reprises. Un échec repris n'y est plus : c'est sa reprise qui dit où en est la ville.
    """
    rows = [{**passage, "raison": passage["raison_attente"]} for passage in queued + waiting]
    rows += [{**passage, "raison": f"échec : {passage['raison_echec']}"} for passage in failed if not passage["repris_par"]]
    return rows


def list_passages(limit: int = 20, item_type: str | None = None, item_id: int | None = None) -> dict:
    """
    Le passage en cours, la file d'attente, les derniers passages finis ou en échec, et les villes non faites avec
    leur raison (villes_en_attente, #211).
    Avec un objet (item_type et item_id) : la même forme, réduite aux passages qui ont ajouté ou modifié cet objet,
    chacun avec ses trouvailles sur lui seul (passages_touching). Lève ValueError pour un objet incomplet ou inconnu.
    """
    if item_type is not None or item_id is not None:
        return passages_touching(item_type, item_id, limit)

    def read_all(ids: list) -> list:
        return [passage for passage in (read_passage(passage_id, details=False) for passage_id in ids) if passage]

    running = read_all(passage_store.passage_ids(RUNNING, limit))
    queued = read_all(passage_store.passage_ids(QUEUED, limit))
    waiting = read_all(passage_store.passage_ids(WAITING, limit))
    failed = read_all(passage_store.passage_ids(FAILED, limit))
    return {"en_cours": [passage for passage in running if passage["etat"] == RUNNING],
            "en_file": queued,
            "derniers": read_all(passage_store.recent_ids(limit)),
            "villes_en_attente": not_done(queued, waiting, failed)}


def passages_touching(item_type: str | None, item_id: int | None, limit: int) -> dict:
    """
    Pour une information (un service, un spot, une pépite), les passages qui l'ont apportée, du plus récent au plus
    ancien, rangés comme la liste des passages. Un passage sans ligne dans passages (ligne de commande, voyageur) va
    dans « derniers ». Lève ValueError pour un objet incomplet ou d'un type inconnu.
    """
    if item_type not in passage_store.ITEM_TYPES or item_id is None:
        raise ValueError(f"Objet incomplet ou inconnu : objet attendu parmi {', '.join(passage_store.ITEM_TYPES)}, "
                         f"avec objet_id")
    item = (item_type, item_id)
    passages = [read_passage(passage_id, item=item) or untracked_passage(passage_id, item)
                for passage_id in passage_store.passages_of_item(item_type, item_id)[:limit]]

    def having(*states) -> list:
        return [passage for passage in passages if passage["etat"] in states]
    return {"en_cours": having(RUNNING), "en_file": having(QUEUED), "derniers": having(DONE, FAILED, None),
            "villes_en_attente": not_done(having(QUEUED), having(WAITING), having(FAILED))}
