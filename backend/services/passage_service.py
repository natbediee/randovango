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
CHAINS donne, pour chaque chaîne, ses catégories, son verrou et la façon de faire passer une catégorie. Seule la chaîne
des services y est branchée ; les autres (OSM, pépites, carburants...) s'y ajouteront avec #276, sans nouvelle route.

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
from agents.service_chain import RegisterUnavailable, interrupted_trace
from services import budget_service, passage_store, service_store
from services.passage_store import DONE, FAILED, QUEUED, RUNNING, TO_DO
from utils.logger_util import LoggerUtil

logger = LoggerUtil.get_logger("passages")

ORIGINS = ("supervision", "etl")    # qui a demandé le passage : l'administratrice, ou l'ETL d'une nouvelle ville (#211)
SAVING = "enregistrement"            # l'étape de l'enregistrement, que le code note lui-même : elle n'appelle aucun agent


class PassageConflict(RuntimeError):
    """Le passage ne peut pas partir maintenant : un autre tourne, ou il n'y a rien à reprendre. Le message le dit."""


@dataclass(frozen=True)
class Chain:
    """Une chaîne d'agents qu'on peut lancer sur une ville."""
    key: str
    label: str
    parts: dict                 # {clé de la catégorie : son libellé}, dans l'ordre où elles passent
    paid: bool                  # payante (des agents) ou gratuite (OSM, fichiers de l'État)
    lock: Callable              # le verrou « un seul passage à la fois » : un bloc « with »
    lock_is_free: Callable      # () -> le verrou est-il libre ?
    run_part: Callable          # (passage_id, clé, ville, reprise) -> le bilan de la catégorie
    steps_of: Callable          # (clé) -> {agent : l'étape qu'il fait}, pour lire l'étape dans llm_calls


# --- La chaîne des services ---

SERVICE_CATEGORIES = {category.key: category for category in find_services.CATEGORIES}
SERVICE_LABELS = {"restaurants": "Recherche des restaurants", "commerces": "Recherche des commerces",
                  "supermarches": "Recherche des supermarchés", "laveries": "Recherche des laveries"}


def run_service_category(passage_id: str, key: str, city: dict, resume: bool) -> dict:
    """
    Une catégorie de la chaîne des services : ses trois agents cherchent, analysent et prouvent, puis le code enregistre.
    En reprise, le fichier d'un passage arrêté en route est repris : ses zones finies ne sont pas repayées.
    """
    category = SERVICE_CATEGORIES[key]
    stopped = interrupted_trace(category, city) if resume else None
    return find_services.search_and_save(
        category, city, stopped=stopped,
        before_saving=lambda: passage_store.set_part(passage_id, key, RUNNING, step=SAVING))


def service_steps(key: str) -> dict:
    """Les trois agents d'une catégorie (service_category.py) et l'étape que fait chacun."""
    return {f"find_{key}": "recherches", f"analyze_{key}": "analyse", f"prove_{key}": "preuves"}


CHAINS = {
    "services": Chain(key="services", label="Recherche des services", parts=SERVICE_LABELS, paid=True,
                      lock=find_services.single_passage, lock_is_free=find_services.lock_is_free,
                      run_part=run_service_category, steps_of=service_steps),
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
    if isinstance(error, PassageRunning):
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


def check_free(chain: Chain) -> None:
    """Lève PassageConflict, avec un message qui le nomme, si un passage de cette chaîne tourne déjà."""
    if chain.lock_is_free():
        return
    running = passage_store.passage_ids(RUNNING, 1)
    passage = passage_store.load_passage(running[0]) if running else None
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
        check_free(chain)
        check_budget(chain)
    # Les catégories passent toujours dans l'ordre de la chaîne : la suivante trouve en base ce que la précédente a écrit.
    chosen = [part for part in chain.parts if not parts or part in parts]
    passage_id = new_passage_id()
    passage_store.insert_passage(passage_id, chain_key, city_id, origin, chosen, resumed_from, status)
    logger.info(f"[passages] {passage_id} demandé ({status}) : {chain_key}, ville {city_id}, {chosen}, origine {origin}")
    return passage_id


def run_passage(passage_id: str) -> None:
    """
    Fait tourner un passage en file, catégorie après catégorie, sous le verrou de sa chaîne. Ne lève jamais : c'est une
    tâche de fond, personne n'attend sa réponse. Un échec est écrit dans la trace, avec sa raison ; les catégories
    finies avant lui restent enregistrées, et celles d'après restent « à faire », pour la reprise.
    Si le verrou est pris, le passage reste en file, sans échec : la file le relancera après le passage en cours (#211).
    """
    passage = passage_store.load_passage(passage_id)
    chain = CHAINS[passage["chain"]]
    resume = passage["resumed_from"] is not None
    part = None
    try:
        # La chaîne des services cherche une commune depuis une seule de ses villes : Morgat se cherche comme Crozon.
        city = service_store.load_city(passage["city_name"])
        with chain.lock(), mesure_passage(passage_id):
            # Relu sous le verrou : la file et la tâche de fond de la supervision peuvent viser le même passage ;
            # le second à prendre le verrou le trouve déjà fini et ne le refait pas.
            if passage_store.load_passage(passage_id)["status"] != QUEUED:
                return
            passage_store.set_passage_status(passage_id, RUNNING)
            for part in [row["part"] for row in passage_store.load_parts(passage_id) if row["status"] == TO_DO]:
                passage_store.set_part(passage_id, part, RUNNING)
                summary = chain.run_part(passage_id, part, city, resume)
                passage_store.set_part(passage_id, part, DONE, summary=summary)
            part = None
        passage_store.set_passage_status(passage_id, DONE)
        logger.info(f"[passages] {passage_id} fini")
    except PassageRunning:
        # Le verrou était pris avant que le passage commence : il garde sa place dans la file.
        logger.info(f"[passages] {passage_id} attend : un autre passage tient le verrou")
    except Exception as error:
        reason = failure_reason(error)
        logger.exception(f"[passages] {passage_id} en échec ({part or 'avant la première catégorie'}) : {reason}")
        if part:
            passage_store.set_part(passage_id, part, FAILED, error=reason)
        passage_store.set_passage_status(passage_id, FAILED, reason)


def resume_passage(passage_id: str, origin: str = "supervision") -> str | None:
    """
    Crée la reprise d'un passage en échec et renvoie son identifiant : seules ses catégories non finies repassent.
    None si le passage n'existe pas ; PassageConflict s'il n'est pas en échec, ou si un autre passage tourne.
    """
    passage = read_passage(passage_id)
    if passage is None:
        return None
    if passage["etat"] != FAILED:
        raise PassageConflict(f"Ce passage est « {passage['etat']} » : seul un passage en échec se reprend.")
    # Une reprise à la fois : les reprises forment une seule ligne (aaa, puis bbb qui reprend aaa, puis ccc qui reprend
    # bbb). L'écran sait ainsi qu'un échec déjà repris n'attend plus rien : sa reprise dit où en est la ville.
    if passage["repris_par"]:
        raise PassageConflict(f"Ce passage a déjà été repris par {passage['repris_par']} : reprendre celui-là s'il a échoué.")
    left = [part["cle"] for part in passage["categories"] if part["etat"] != DONE]
    return create_passage(passage["chaine"], passage["ville"]["id"], left, origin, resumed_from=passage_id)


# --- Dire où il en est ---

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
    """Le nombre d'appels, d'appels ratés et le coût d'une liste d'appels de llm_calls."""
    return {"appels": len(calls), "echecs_appels": sum(call["status"] != "reussi" for call in calls),
            "cout_usd": round(sum(float(call["cost_usd"] or 0) for call in calls), 4)}


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


def summary_text(summary: dict | None) -> str | None:
    """
    Le bilan d'une catégorie en une phrase, pour l'écran : « 3 services enregistrés ; 1 même nom ailleurs dans la
    commune, à relire comme doublon possible. » Les cases à zéro ne sont pas dites ; une clé inconnue garde son nom,
    pour ne rien perdre. None tant que la catégorie n'a pas été enregistrée.
    """
    if summary is None:
        return None
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
        step = steps[last["agent"]] if last else "recherches"
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
    if passage["status"] == RUNNING and chain.lock_is_free():
        mark_interrupted(passage, parts)
    calls = passage_store.load_calls(passage_id)
    return {"passage_id": passage_id, "chaine": chain.key, "libelle_chaine": chain.label,
            "ville": {"id": passage["city_id"], "nom": passage["city_name"], "commune": passage["city_commune"]},
            "origine": passage["origin"], "etat": passage["status"], "payant": chain.paid,
            "demande_le": passage["requested_at"], "debut": passage["started_at"], "fin": passage["finished_at"],
            "raison_echec": passage["error"], "reprise_de": passage["resumed_from"],
            "repris_par": passage_store.resumed_by(passage_id), **call_totals(calls),
            "categories": [part_state(chain, part, calls) for part in parts]}


def list_passages(limit: int = 20) -> dict:
    """Le passage en cours, la file d'attente (remplie par #211) et les derniers passages finis ou en échec."""
    def read_all(ids: list) -> list:
        return [passage for passage in map(read_passage, ids) if passage]

    running = read_all(passage_store.passage_ids(RUNNING, limit))
    return {"en_cours": [passage for passage in running if passage["etat"] == RUNNING],
            "en_file": read_all(passage_store.passage_ids(QUEUED, limit)),
            "derniers": read_all(passage_store.recent_ids(limit))}
