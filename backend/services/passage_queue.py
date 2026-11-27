"""
La file des passages : chaque étape fait partir, l'une après l'autre, les villes qui l'attendent (issues #211, #332).

POURQUOI UNE FILE
Une nouvelle ville ajoutée par l'envoi d'une rando demande ses chaînes : OSM, carburants, FINESS, spots, pépites,
services. Elles ne partent pas toutes en même temps : elles restent « en file » dans la table passages, et partent
dès que c'est possible, dans l'ordre où les villes sont arrivées.

UNE FILE PAR ÉTAPE (issue #332)
Avant #332, un seul fil prenait les passages chaîne par chaîne pour toutes les villes : avec 192 villes envoyées le
25 novembre 2026 au soir, aucun agent n'a tourné de la nuit, et chaque nouvel envoi repoussait les agents des villes
déjà en file. Désormais, chaque étape (services/passage_steps.py) a son propre fil de fond :
    - il prend une ville à la fois, du passage le plus ancien au plus récent ;
    - il saute une ville qui n'est pas prête pour lui (son OSM pas fini, sa source des spots pas lue) et prend la
      suivante : une ville en échec ne fait attendre qu'elle-même ;
    - il n'attend jamais les étapes d'après : OSM enchaîne les villes pendant que les pépites et les services de la
      première tournent encore.
Comme le fil OSM ne prend qu'une ville à la fois, Overpass n'est interrogé que pour une ville à la fois.

LES ÉTAPES PAYANTES ATTENDENT SANS ÉCHOUER
Quand le quota des agents ou leur budget est atteint, les fils payants (agents des spots, pépites, services)
attendent ; les fils gratuits continuent. Une partie coupée en route par une limite du fournisseur des agents retourne
en file (services/agents_pause.py) : à l'heure de retour donnée par le fournisseur, son fil la reprend, sans repayer ce
qui est fait.

LES CHAÎNES GRATUITES SE REPRENNENT SEULES (issue #316)
Un OSM, des carburants ou un FINESS de l'ETL en échec est repris par la file un quart d'heure plus tard, deux fois au
plus (resume_failed_free_chains), par un fil à part. Une chaîne payante en échec, elle, attend toujours l'admin.

COMMENT
Les fils sont lancés au démarrage de l'API (start_worker). Chacun regarde sa file toutes les minutes, et tout de suite
quand on le réveille (wake) : l'ETL vient d'y mettre une ville, l'admin a repris un passage, ou une autre étape vient
de finir une ville. Le budget du lendemain, ou un budget relevé par l'admin, est donc vu au plus tard une minute après.
La file est la table passages elle-même : après un redémarrage du serveur, les passages en file y sont toujours, et
les fils repartent d'eux. Pas besoin d'un outil de plus (Celery, Redis).
"""
import threading
from datetime import datetime, timedelta

from services import passage_service, passage_steps, passage_store
from services.passage_steps import Step
from utils.logger_util import LoggerUtil

logger = LoggerUtil.get_logger("passages")

CHECK_SECONDS = 60          # le temps entre deux regards sur une file, quand personne ne la réveille

# La reprise seule des chaînes gratuites (issue #316). Un échec d'OSM, des carburants ou de FINESS vient presque
# toujours d'une panne passagère (OpenStreetMap saturé, fichier de 52 Mo coupé en route) : la file le reprend elle-même,
# comme le bouton de la supervision, au lieu d'un script lancé à la main (25 novembre 2026 : trois tours de reprise).
AUTO_RESUMED_CHAINS = ("osm", "carburants", "finess")
RESUME_AFTER_MINUTES = 15       # le temps laissé au serveur pour se remettre avant de reprendre
MAX_AUTO_RESUMES = 2            # deux reprises au plus : trois essais en tout, puis l'échec attend l'admin
AUTO_RESUME_HOURS = 24          # un échec plus ancien n'est pas repris seul : l'admin a peut-être déjà décidé

RESUMES = "reprises"            # le nom du fil qui reprend les chaînes gratuites en échec
# Un réveil par fil : posé par wake(), il fait regarder la file sans attendre la fin de la minute.
_wakes = {key: threading.Event() for key in [*passage_steps.STEPS_BY_KEY, RESUMES]}
_workers = []               # les fils de fond, une fois lancés


def why_waiting(passage_id: str) -> str | None:
    """Pourquoi ce passage en file ne peut pas partir maintenant (étape d'avant, verrou, quota, budget) ; None s'il peut."""
    return passage_service.waiting_reason(passage_store.load_passage(passage_id))


# --- Une étape ---

def is_ready(step: Step, row: dict) -> bool:
    """
    La ville de ce passage en file est-elle prête pour l'étape : l'étape d'avant finie pour elle, et le verrou de la
    chaîne libre pour cette partie (un passage lancé en ligne de commande peut le tenir) ?
    """
    passage = passage_store.load_passage(row["passage_id"])
    if passage is None or passage_steps.missing_need(step, passage):
        return False
    return passage_service.CHAINS[step.chain].lock_is_free(row["city_id"], row["next_part"])


def next_for(step: Step) -> str | None:
    """
    Le prochain passage que l'étape fait partir : le plus ancien de sa file dont la ville est prête ; None si sa file
    est vide, si aucune ville n'est prête, ou si l'étape est payante et que la limite des agents ou le budget la retient.
    Un passage est dans la file de l'étape quand sa prochaine partie à faire est à elle.
    """
    if step.paid:
        reason = passage_service.paid_wait()
        if reason:
            logger.info(f"[file {step.key}] attend : {reason}")
            return None
    for row in passage_store.queued_next_parts():
        if row["next_part"] is None or passage_steps.step_for(row["chain"], row["next_part"]) is not step:
            continue
        if is_ready(step, row):
            return row["passage_id"]
    return None


def run_step_once(step: Step) -> bool:
    """
    Fait partir le prochain passage de l'étape (next_for) et attend sa fin. Renvoie True s'il en a fait partir un (il y
    en a peut-être un autre derrière), False sinon. Une fois la ville finie, les autres étapes sont réveillées : celles
    qui attendaient cette ville (les carburants après son OSM, les agents des spots après sa source) la prennent.
    """
    passage_id = next_for(step)
    if passage_id is None:
        return False
    logger.info(f"[file {step.key}] {passage_id} part")
    passage_service.run_passage(passage_id, list(step.parts) if step.parts else None)
    wake()
    return True


def work_on_step(step: Step) -> None:
    """
    Le travail du fil d'une étape : faire partir ses passages tant qu'il y en a un prêt, puis attendre une minute ou un
    réveil. Une erreur (base injoignable un instant) est notée dans le journal et n'arrête pas le fil.
    """
    while True:
        try:
            while run_step_once(step):
                pass
        except Exception:
            logger.exception(f"[file {step.key}] erreur en regardant la file : nouvel essai au prochain tour")
        _wakes[step.key].wait(CHECK_SECONDS)
        _wakes[step.key].clear()


# --- La reprise seule des chaînes gratuites en échec (issue #316) ---

def resumes_before(failure: dict) -> int:
    """Combien de reprises ont déjà mené à cet échec : on remonte les resumed_from jusqu'au premier passage."""
    count, previous = 0, failure["resumed_from"]
    while previous:
        count += 1
        passage = passage_store.load_passage(previous)
        previous = passage["resumed_from"] if passage else None
    return count


def can_resume_alone(failure: dict, now: datetime) -> bool:
    """
    Un échec que la file reprend seule : fini depuis au moins RESUME_AFTER_MINUTES, moins de MAX_AUTO_RESUMES reprises
    derrière lui, une chaîne pas déjà en file ou en cours sur la ville, et pas déjà finie par un autre passage (une
    relance à la main entre-temps).
    Le cas de la file ou du cours (issue #329) : à Larrau, deux carburants en échec, doublons d'avant #316, avaient été
    repris tous les deux, ce qui mettait deux carburants en file pour la même ville (25 novembre 2026). Le premier
    repris est en file quand vient le second : celui-ci n'est pas repris.
    """
    if failure["finished_at"] > now - timedelta(minutes=RESUME_AFTER_MINUTES):
        return False
    if resumes_before(failure) >= MAX_AUTO_RESUMES:
        return False
    if passage_store.active_ids(failure["chain"], failure["city_id"]):
        return False
    return not passage_store.finished_parts(failure["chain"], [failure["city_id"]])


def resume_failed_free_chains(now: datetime | None = None) -> list:
    """
    Reprend les chaînes gratuites de l'ETL en échec qui peuvent l'être (can_resume_alone) : chaque reprise est un
    nouveau passage en file, d'origine « etl », comme une relance depuis la supervision. Rend leurs identifiants.
    """
    now = now or datetime.now()
    since = now - timedelta(hours=AUTO_RESUME_HOURS)
    resumed = []
    for failure in passage_store.failures_to_resume(AUTO_RESUMED_CHAINS, since):
        if not can_resume_alone(failure, now):
            continue
        passage_id = passage_service.resume_passage(failure["passage_id"], origin="etl")
        logger.info(f"[file] {failure['passage_id']} en échec repris seul par {passage_id}")
        resumed.append(passage_id)
    return resumed


def work_on_resumes() -> None:
    """
    Le travail du fil des reprises : reprendre les chaînes gratuites en échec qui peuvent l'être, réveiller les étapes
    s'il en a repris, puis attendre une minute. Un seul fil le fait : deux fils pourraient reprendre le même échec.
    """
    while True:
        try:
            if resume_failed_free_chains():
                wake()
        except Exception:
            logger.exception("[file] erreur en reprenant les échecs : nouvel essai au prochain tour")
        _wakes[RESUMES].wait(CHECK_SECONDS)
        _wakes[RESUMES].clear()


def wake() -> None:
    """Demande à tous les fils de regarder leur file tout de suite : une ville y est entrée, ou une étape a fini."""
    for event in _wakes.values():
        event.set()


def start_worker() -> None:
    """
    Lance les fils de fond, un par étape et celui des reprises, une seule fois par programme. Des fils « daemon »
    s'arrêtent avec l'API.
    """
    if _workers:
        return
    for step in passage_steps.STEPS:
        _workers.append(threading.Thread(target=work_on_step, args=(step,), name=f"file-{step.key}", daemon=True))
    _workers.append(threading.Thread(target=work_on_resumes, name="file-reprises", daemon=True))
    for worker in _workers:
        worker.start()
    logger.info(f"[file] {len(_workers)} fils de la file des passages lancés")
