"""
La file des passages : elle fait partir, l'un après l'autre, les passages qui attendent leur tour (issue #211).

POURQUOI UNE FILE
Une nouvelle ville ajoutée par l'ETL demande un passage de la chaîne des services. Si un autre passage tourne déjà
(une seule recherche à la fois, verrou de MySQL), ou si le budget des agents est atteint, le passage n'est pas perdu :
il reste « en file » dans la table passages, et part dès que c'est possible. Deux villes ajoutées coup sur coup passent
ainsi l'une après l'autre, dans l'ordre où elles sont arrivées.

LES CHAÎNES RAPIDES D'ABORD (issue #316)
Un envoi de 70 randos met dans la file, pour chaque ville, OSM, les carburants, FINESS, les spots, les pépites et les
services. Pris dans l'ordre d'arrivée, la ville B attendrait les services de la ville A, qui durent des heures. La file
prend donc les passages chaîne par chaîne, dans l'ordre de CHAIN_ORDER : tous les OSM, puis tous les carburants, et
ainsi de suite ; dans une même chaîne, du plus ancien au plus récent. Pour chaque ville, l'ordre de l'ajout d'une ville
est gardé : FINESS après OSM (les noms des pharmacies), les pépites après les spots, les services en dernier.

LES CHAÎNES GRATUITES SE REPRENNENT SEULES (issue #316)
Un OSM, des carburants ou un FINESS de l'ETL en échec est repris par la file un quart d'heure plus tard, deux fois au
plus (resume_failed_free_chains). Une chaîne payante en échec, elle, attend toujours l'admin : une reprise coûte.

COMMENT
Un fil de fond, lancé au démarrage de l'API (start_worker), regarde la file toutes les minutes, et tout de suite quand
l'ETL vient d'y mettre une ville (wake). À chaque tour, il fait partir le premier passage en file, si le verrou de
sa chaîne est libre et si le budget le permet ; sinon il attend le tour suivant. Le budget du lendemain, ou un budget
relevé par l'admin, est donc vu au plus tard une minute après.
La file est la table passages elle-même : après un redémarrage du serveur, les passages en file y sont toujours, et le
fil repart d'eux. Pas besoin d'un outil de plus (Celery, Redis) pour un passage à la fois.
"""
import threading
from datetime import datetime, timedelta

from services import passage_service, passage_store
from utils.logger_util import LoggerUtil

logger = LoggerUtil.get_logger("passages")

CHECK_SECONDS = 60          # le temps entre deux regards sur la file, quand personne ne la réveille

# L'ordre dans lequel la file fait passer les chaînes : les gratuites et rapides d'abord, les services en dernier.
CHAIN_ORDER = ("osm", "carburants", "finess", "spots", "pepites", "services")

# La reprise seule des chaînes gratuites (issue #316). Un échec d'OSM, des carburants ou de FINESS vient presque
# toujours d'une panne passagère (OpenStreetMap saturé, fichier de 52 Mo coupé en route) : la file le reprend elle-même,
# comme le bouton de la supervision, au lieu d'un script lancé à la main (25 novembre 2026 : trois tours de reprise).
AUTO_RESUMED_CHAINS = ("osm", "carburants", "finess")
RESUME_AFTER_MINUTES = 15       # le temps laissé au serveur pour se remettre avant de reprendre
MAX_AUTO_RESUMES = 2            # deux reprises au plus : trois essais en tout, puis l'échec attend l'admin
AUTO_RESUME_HOURS = 24          # un échec plus ancien n'est pas repris seul : l'admin a peut-être déjà décidé

_wake = threading.Event()   # posé par wake() : le fil regarde la file sans attendre la fin de la minute
_worker = None              # le fil de fond, une fois lancé


def why_waiting(passage_id: str) -> str | None:
    """Pourquoi ce passage en file ne peut pas partir maintenant (verrou pris, budget atteint) ; None s'il peut partir."""
    return passage_service.waiting_reason(passage_store.load_passage(passage_id))


def chain_rank(chain_key: str) -> int:
    """Le rang d'une chaîne dans la file (0 pour OSM) ; une chaîne absente de CHAIN_ORDER passe en dernier."""
    if chain_key in CHAIN_ORDER:
        return CHAIN_ORDER.index(chain_key)
    return len(CHAIN_ORDER)


def queue_in_order() -> list:
    """
    Les passages en file, dans l'ordre où la file les essaie : chaîne par chaîne (CHAIN_ORDER), puis du plus ancien au
    plus récent. queued_ids les donne déjà du plus ancien au plus récent, et « sorted » garde cet ordre entre deux
    passages de la même chaîne (on dit que le tri est stable).
    """
    passages = [passage_store.load_passage(passage_id) for passage_id in passage_store.queued_ids()]
    return sorted([passage for passage in passages if passage], key=lambda passage: chain_rank(passage["chain"]))


def run_next() -> bool:
    """
    Fait partir le premier passage en file qui peut partir, dans l'ordre de queue_in_order, et attend sa fin. Renvoie
    True s'il en a fait partir un (il y en a peut-être un autre derrière), False si la file est vide ou si tous doivent
    encore attendre.
    Un passage qui attend ne retient pas ceux d'après : un passage gratuit (OSM, carburants) part même quand un passage
    des services, plus ancien, attend le budget du lendemain.
    """
    for passage in queue_in_order():
        passage_id = passage["passage_id"]
        reason = passage_service.waiting_reason(passage)
        if reason:
            logger.info(f"[file] {passage_id} attend : {reason}")
            continue
        logger.info(f"[file] {passage_id} part")
        passage_service.run_passage(passage_id)
        return True
    return False


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


def work_forever() -> None:
    """
    Le travail du fil de fond : reprendre les chaînes gratuites en échec qui peuvent l'être, faire partir un passage,
    et recommencer tant que la file en a un prêt ; puis attendre une minute ou un réveil. Une erreur (base injoignable
    un instant) est notée dans le journal et n'arrête pas le fil : il réessaie au tour suivant.
    """
    while True:
        try:
            # Les reprises sont regardées avant chaque passage : pendant les heures d'un long envoi, un OSM en échec
            # reprend sa place sans attendre que la file soit vide.
            resume_failed_free_chains()
            while run_next():
                resume_failed_free_chains()
        except Exception:
            logger.exception("[file] erreur en regardant la file : nouvel essai au prochain tour")
        _wake.wait(CHECK_SECONDS)
        _wake.clear()


def wake() -> None:
    """Demande au fil de regarder la file tout de suite : l'ETL vient d'y mettre une ville."""
    _wake.set()


def start_worker() -> None:
    """Lance le fil de fond, une seule fois par programme. Un fil « daemon » s'arrête avec l'API."""
    global _worker
    if _worker is not None:
        return
    _worker = threading.Thread(target=work_forever, name="file-des-passages", daemon=True)
    _worker.start()
    logger.info("[file] fil de la file des passages lancé")
