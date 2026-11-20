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
carburants (services/etl_chains.py). Les autres (spots, pépites) s'y ajouteront, toujours sans nouvelle route.

REPRENDRE SANS REPAYER
Un passage en échec garde ce qui est fini. resume_passage en crée un nouveau, qui ne refait que les catégories non
finies ; une grande ville cherchée par zones reprend en plus les zones finies de son fichier (service_chain).
Le passage en échec reste tel quel, trace fidèle de ce qui s'est passé : la reprise le désigne (resumed_from), et lui
connaît sa reprise (repris_par). Un passage ne se reprend qu'une fois : si la reprise échoue, c'est elle qu'on reprend.
"""
import re
from dataclasses import dataclass
from typing import Callable

from agents import find_services
from agents.find_services import PassageRunning
from agents.llm_service import LLMRefused, LLMTimeout, mesure_passage, new_passage_id
from agents.service_chain import RegisterUnavailable, interrupted_trace, latest_traces
from services import budget_service, etl_chains, llm_calls_service, passage_store, service_store
from services.etl_chains import StepFailed
from services.passage_store import DONE, FAILED, QUEUED, RUNNING, TO_DO, WAITING
from utils.geo_utils import city_commune
from utils.logger_util import LoggerUtil

logger = LoggerUtil.get_logger("passages")

ORIGINS = ("supervision", "etl")    # qui a demandé le passage : l'administratrice, ou l'ETL d'une nouvelle ville (#211)
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
    lock: Callable              # (id de la ville) -> le verrou « un seul passage à la fois » : un bloc « with »
    lock_is_free: Callable      # (id de la ville) -> le verrou est-il libre ?
    run_part: Callable          # (passage_id, clé, ville, reprise, vérification du budget) -> le bilan de la catégorie
    steps_of: Callable          # (clé) -> {agent : l'étape qu'il fait}, pour lire l'étape dans llm_calls
    # False : un seul passage à la fois, toutes villes confondues, sur la commune de la ville (Morgat se cherche comme
    # Crozon). True : un passage à la fois par ville, sur la ville elle-même (les chaînes gratuites de l'ETL).
    per_city: bool = False


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
                 lock=lambda city_id: etl_chains.city_lock(key, city_id),
                 lock_is_free=lambda city_id: etl_chains.city_lock_is_free(key, city_id),
                 run_part=run_part, steps_of=lambda part: {}, per_city=True)


CHAINS = {
    # La chaîne des services ne regarde pas la ville pour son verrou : un seul passage à la fois, partout.
    "services": Chain(key="services", label="Recherche des services", parts=SERVICE_LABELS, paid=True,
                      lock=lambda city_id: find_services.single_passage(),
                      lock_is_free=lambda city_id: find_services.lock_is_free(),
                      run_part=run_service_category, steps_of=service_steps),
    "osm": free_chain("osm", "Lieux d'OpenStreetMap", "Lieux d'OpenStreetMap", etl_chains.run_osm),
    "finess": free_chain("finess", "Pharmacies du registre FINESS", "Pharmacies du registre FINESS",
                         etl_chains.run_finess),
    "carburants": free_chain("carburants", "Stations-service et carburants", "Stations-service et prix des carburants",
                             etl_chains.run_fuel),
}


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
API_BUSY = re.compile(r"rate.?limit|overloaded|Error code: (429|529)", re.IGNORECASE)
REASON_LENGTH = 255         # la longueur des colonnes error


def failure_reason(error: Exception) -> str:
    """
    La raison d'un échec, telle que l'administratrice la lit. Les cas connus sont traduits ; un cas inconnu garde le
    message d'origine, pour qu'on puisse le chercher dans les journaux.
    """
    message = str(error)
    if isinstance(error, StepFailed):
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


def check_free(chain: Chain, city_id: int) -> None:
    """
    Lève PassageConflict, avec un message qui le nomme, si un passage de cette chaîne tourne déjà (sur cette ville,
    pour une chaîne qui a un verrou par ville).
    """
    if chain.lock_is_free(city_id):
        return
    # Le passage en cours de cette chaîne, et pas d'une autre : le message nomme celui qui tient le verrou.
    running = [passage_store.load_passage(passage_id) for passage_id in passage_store.running_ids(chain.key)]
    if chain.per_city:
        running = [passage for passage in running if passage and passage["city_id"] == city_id]
    passage = running[0] if running else None
    if passage:
        raise PassageConflict(f"Un passage « {chain.label} » tourne déjà sur {passage['city_name']}, depuis le "
                              f"{passage['started_at']:%d/%m/%Y à %H h %M} : attendre sa fin avant d'en lancer un autre.")
    # Le verrou est tenu sans trace : le passage a été lancé à la main dans le conteneur.
    raise PassageConflict(f"Un passage « {chain.label} » tourne déjà, lancé en ligne de commande : attendre sa fin.")


def check_budget(chain: Chain) -> None:
    """
    Lève PassageConflict, avec la raison, si le budget des agents est atteint (issue #211) : un passage payant ne part
    pas, même lancé à la main, tant que le budget ne le permet pas de nouveau ou que l'admin ne le relève pas.
    Une chaîne gratuite (OSM, fichiers de l'État) n'est jamais retenue par le budget.
    """
    if not chain.paid:
        return
    reason = budget_service.budget_block()
    if reason:
        raise PassageConflict(f"Budget des agents atteint ({reason}).")


def stop_if_over_budget(chain: Chain) -> None:
    """
    Pendant un passage, avant chaque catégorie et chaque zone d'une grande ville : lève BudgetReached si le budget des
    agents est atteint. Le budget n'est donc jamais dépassé de plus d'une zone, ou d'une catégorie d'une petite ville.
    """
    if not chain.paid:
        return
    reason = budget_service.budget_block()
    if reason:
        raise BudgetReached(reason)


def create_passage(chain_key: str, city_id: int, parts: list | None = None, origin: str = "supervision",
                   resumed_from: str | None = None, status: str = QUEUED) -> str:
    """
    Écrit un passage demandé, en file, et renvoie son identifiant. Sans catégories, toutes celles de la chaîne.
    Lève ValueError pour une chaîne, une ville, une catégorie ou une origine inconnue.
    Lancé depuis la supervision, il est refusé (PassageConflict) si un passage de la chaîne tourne déjà ou si le budget
    des agents est atteint : l'admin le sait tout de suite. Demandé par l'ETL, il n'est jamais refusé : il prend sa
    place dans la file, et la file le lance quand le verrou et le budget le permettent (passage_queue.py, #211).
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
    if origin == "supervision":
        check_free(chain, city_id)
        check_budget(chain)
    # Les catégories passent toujours dans l'ordre de la chaîne : la suivante trouve en base ce que la précédente a écrit.
    chosen = [part for part in chain.parts if not parts or part in parts]
    passage_id = new_passage_id()
    passage_store.insert_passage(passage_id, chain_key, city_id, origin, chosen, resumed_from, status)
    logger.info(f"[passages] {passage_id} demandé ({status}) : {chain_key}, ville {city_id}, {chosen}, origine {origin}")
    return passage_id


def city_to_run(chain: Chain, passage: dict) -> dict:
    """
    La ville sur laquelle la chaîne travaille. La chaîne des services cherche une commune depuis une seule de ses
    villes : Morgat se cherche comme Crozon. Une chaîne gratuite charge la ville elle-même : l'OSM de Morgat est le sien.
    """
    if chain.per_city:
        return {"id": passage["city_id"], "name": passage["city_name"]}
    return service_store.load_city(passage["city_name"])


def run_passage(passage_id: str) -> None:
    """
    Fait tourner un passage en file, catégorie après catégorie, sous le verrou de sa chaîne. Ne lève jamais : c'est une
    tâche de fond, personne n'attend sa réponse. Un échec est écrit dans la trace, avec sa raison ; les catégories
    finies avant lui restent enregistrées, et celles d'après restent « à faire », pour la reprise.
    Si le verrou est pris, le passage reste en file, sans échec : la file le relancera après le passage en cours (#211).
    Si le budget est atteint en route, le passage s'arrête avant la catégorie ou la zone suivante et retourne en file :
    ce qui est fini reste enregistré, et la file le reprendra là où il en était quand le budget le permettra.
    """
    passage = passage_store.load_passage(passage_id)
    chain = CHAINS[passage["chain"]]
    resume = passage["resumed_from"] is not None
    part = None
    try:
        city = city_to_run(chain, passage)
        with chain.lock(passage["city_id"]), mesure_passage(passage_id):
            # Relu sous le verrou : la file et la tâche de fond de la supervision peuvent viser le même passage ;
            # le second à prendre le verrou le trouve déjà fini et ne le refait pas.
            if passage_store.load_passage(passage_id)["status"] != QUEUED:
                return
            passage_store.set_passage_status(passage_id, RUNNING)
            for row in [row for row in passage_store.load_parts(passage_id) if row["status"] == TO_DO]:
                part = row["part"]
                stop_if_over_budget(chain)
                passage_store.set_part(passage_id, part, RUNNING)
                # Une catégorie arrêtée par le budget reprend son fichier : ses zones finies ne sont pas repayées.
                summary = chain.run_part(passage_id, part, city, resume or row["step"] == PAUSED,
                                         lambda: stop_if_over_budget(chain))
                passage_store.set_part(passage_id, part, DONE, summary=summary)
            part = None
        passage_store.set_passage_status(passage_id, DONE)
        logger.info(f"[passages] {passage_id} fini")
    except PassageRunning:
        # Le verrou était pris avant que le passage commence : il garde sa place dans la file.
        logger.info(f"[passages] {passage_id} attend : un autre passage tient le verrou")
    except BudgetReached as reason:
        # Pas un échec : le passage retourne en file, et la catégorie arrêtée garde l'étape « budget » pour la reprise.
        logger.info(f"[passages] {passage_id} arrêté avant {part} : {reason}")
        passage_store.set_part(passage_id, part, TO_DO, step=PAUSED)
        passage_store.set_passage_status(passage_id, QUEUED)
    except Exception as error:
        reason = failure_reason(error)
        logger.exception(f"[passages] {passage_id} en échec ({part or 'avant la première catégorie'}) : {reason}")
        if part:
            passage_store.set_part(passage_id, part, FAILED, error=reason)
        passage_store.set_passage_status(passage_id, FAILED, reason)


def searched_service_categories(cities: list) -> set:
    """
    Les catégories de services déjà cherchées jusqu'au bout pour une commune (ses villes : `cities`), d'après les
    fichiers des passages des agents. Les fichiers, et pas la table passages : les communes cherchées en ligne de
    commande, avant la supervision, n'ont aucune ligne dans passages. Un fichier porte le nom de la commune, ou celui de
    la ville pour un passage d'avant le 8 novembre 2026 (Morgat pour Crozon) : les deux sont regardés.
    """
    names = {city_commune(city) for city in cities} | {city["name"] for city in cities}
    return {key for key, category in SERVICE_CATEGORIES.items() if names & set(latest_traces(category))}


def request_etl_passage(city_name: str) -> str | None:
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
    return create_passage("services", city["id"], left, origin="etl", status=status)


def launch_waiting(passage: dict) -> str:
    """
    Lance une ville que l'ETL a laissée en attente (mise à jour automatique coupée) : le passage est remis en file,
    à sa place, et l'admin le fait partir. Mêmes refus qu'un lancement à la main : verrou pris ou budget atteint.
    """
    chain = CHAINS[passage["chaine"]]
    check_free(chain, passage["ville"]["id"])
    check_budget(chain)
    passage_store.set_passage_status(passage["passage_id"], QUEUED)
    logger.info(f"[passages] {passage['passage_id']} lancé par l'admin après l'attente")
    return passage["passage_id"]


def resume_passage(passage_id: str, origin: str = "supervision") -> str | None:
    """
    La relance d'une ville non faite, par l'admin, et l'identifiant du passage à faire tourner :
    - un passage en échec est repris par un nouveau passage, qui ne refait que ses catégories non finies ;
    - un passage en attente (mise à jour automatique coupée, #211) part lui-même, sans nouveau passage.
    None si le passage n'existe pas ; PassageConflict s'il n'est ni en échec ni en attente, si un autre passage tourne,
    ou si le budget est atteint.
    """
    passage = read_passage(passage_id)
    if passage is None:
        return None
    if passage["etat"] == WAITING:
        return launch_waiting(passage)
    if passage["etat"] != FAILED:
        raise PassageConflict(f"Ce passage est « {passage['etat']} » : seul un passage en échec ou en attente se relance.")
    # Une reprise à la fois : les reprises forment une seule ligne (aaa, puis bbb qui reprend aaa, puis ccc qui reprend
    # bbb). L'écran sait ainsi qu'un échec déjà repris n'attend plus rien : sa reprise dit où en est la ville.
    if passage["repris_par"]:
        raise PassageConflict(f"Ce passage a déjà été repris par {passage['repris_par']} : reprendre celui-là s'il a échoué.")
    left = [part["cle"] for part in passage["categories"] if part["etat"] != DONE]
    return create_passage(passage["chaine"], passage["ville"]["id"], left, origin, resumed_from=passage_id)


# --- Dire où il en est ---

def list_chains() -> list:
    """
    Les chaînes qu'on peut lancer, dans l'ordre de CHAINS : leur clé (à envoyer dans « chaine »), leur libellé, si elles
    sont payantes (des agents, retenues par le budget) ou gratuites, et leurs parties (à envoyer dans « categories »).
    """
    return [{"chaine": chain.key, "libelle": chain.label, "payant": chain.paid,
             "categories": [{"cle": key, "libelle": label} for key, label in chain.parts.items()]}
            for chain in CHAINS.values()]


AUTO_OFF = "mise à jour automatique coupée : à lancer depuis la supervision"


def waiting_reason(passage: dict) -> str | None:
    """
    Pourquoi un passage n'a pas encore tourné, en phrase lisible ; None s'il tourne, a fini, ou peut partir.
    En file : le verrou d'abord (un passage qui tourne passera de toute façon avant lui), puis le budget.
    """
    if passage["status"] == WAITING:
        return AUTO_OFF
    if passage["status"] != QUEUED:
        return None
    chain = CHAINS[passage["chain"]]
    if not chain.lock_is_free(passage["city_id"]):
        return "attend la fin du passage en cours"
    return budget_service.budget_block() if chain.paid else None


def mark_interrupted(passage: dict, parts: list) -> None:
    """
    Un passage « en cours » dont plus personne ne tient le verrou a été coupé : le serveur a redémarré pendant qu'il
    tournait. On l'écrit en échec, une fois pour toutes, pour qu'il puisse être repris.
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


# Le bilan d'une chaîne gratuite (services/etl_chains.py) : ce qu'elle a chargé, (singulier, pluriel).
LOADED_WORDS = {"lieux": ("lieu chargé", "lieux chargés"), "pharmacies": ("pharmacie chargée", "pharmacies chargées"),
                "stations": ("station chargée", "stations chargées")}


def loaded_text(summary: dict) -> str:
    """Le bilan d'une chaîne gratuite en une phrase : « 42 lieux chargés. », « 0 stations chargées. »"""
    pieces = []
    for key, count in summary.items():
        one, many = LOADED_WORDS.get(key, (key, key))
        pieces.append(f"{count} {one if count == 1 else many}" if count else f"0 {many}")
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


def part_state(chain: Chain, part: dict, calls: list) -> dict:
    """
    Ce que l'écran montre d'une catégorie : son état, son étape, son coût, son bilan ou la raison de son échec.
    L'étape vient du dernier appel de ses agents (recherches, analyse, preuves), sauf l'enregistrement, noté par le code.
    """
    steps = chain.steps_of(part["part"])
    mine = [call for call in calls if call["agent"] in steps]
    last = mine[-1] if mine else None
    if part["status"] in (TO_DO, DONE):
        step, detail = None, None
    elif part["step"]:
        step, detail = part["step"], None
    else:
        # Une chaîne sans agent (OSM, FINESS, carburants) n'a qu'une étape : le chargement.
        step = steps[last["agent"]] if last else ("recherches" if steps else LOADING)
        detail = last["etape"] if last else None
    return {"cle": part["part"], "libelle": chain.parts[part["part"]], "payant": chain.paid, "etat": part["status"],
            "etape": step, "detail_etape": detail, "agent": last["agent"] if last and step != SAVING else None,
            **call_totals(mine), "bilan": part["summary"], "bilan_texte": summary_text(part["summary"]),
            "raison_echec": part["error"],
            "debut": part["started_at"], "fin": part["finished_at"]}


def read_passage(passage_id: str) -> dict | None:
    """Tout ce que l'espace Agents de la supervision affiche d'un passage ; None s'il n'existe pas."""
    passage = passage_store.load_passage(passage_id)
    if passage is None:
        return None
    chain = CHAINS[passage["chain"]]
    parts = passage_store.load_parts(passage_id)
    if passage["status"] == RUNNING and chain.lock_is_free(passage["city_id"]):
        mark_interrupted(passage, parts)
    calls = passage_store.load_calls(passage_id)
    return {"passage_id": passage_id, "chaine": chain.key, "libelle_chaine": chain.label,
            "ville": {"id": passage["city_id"], "nom": passage["city_name"], "commune": passage["city_commune"]},
            "origine": passage["origin"], "etat": passage["status"], "payant": chain.paid,
            "demande_le": passage["requested_at"], "debut": passage["started_at"], "fin": passage["finished_at"],
            "raison_echec": passage["error"], "raison_attente": waiting_reason(passage),
            "reprise_de": passage["resumed_from"],
            "repris_par": passage_store.resumed_by(passage_id), **call_totals(calls),
            "categories": [part_state(chain, part, calls) for part in parts]}


def not_done(queued: list, waiting: list, failed: list) -> list:
    """
    Les villes non faites, avec leur raison, pour le tableau « Villes en attente » de l'espace Agents (#211) :
    celles en file (budget atteint, passage en cours), celles en attente de l'admin (mise à jour coupée), et celles en
    échec que personne n'a encore reprises. Un échec repris n'y est plus : c'est sa reprise qui dit où en est la ville.
    """
    rows = [{**passage, "raison": passage["raison_attente"]} for passage in queued + waiting]
    rows += [{**passage, "raison": f"échec : {passage['raison_echec']}"} for passage in failed if not passage["repris_par"]]
    return rows


def list_passages(limit: int = 20) -> dict:
    """
    Le passage en cours, la file d'attente, les derniers passages finis ou en échec, et les villes non faites avec
    leur raison (villes_en_attente, #211).
    """
    def read_all(ids: list) -> list:
        return [passage for passage in map(read_passage, ids) if passage]

    running = read_all(passage_store.passage_ids(RUNNING, limit))
    queued = read_all(passage_store.passage_ids(QUEUED, limit))
    waiting = read_all(passage_store.passage_ids(WAITING, limit))
    failed = read_all(passage_store.passage_ids(FAILED, limit))
    return {"en_cours": [passage for passage in running if passage["etat"] == RUNNING],
            "en_file": queued,
            "derniers": read_all(passage_store.recent_ids(limit)),
            "villes_en_attente": not_done(queued, waiting, failed)}
