"""
La file des passages : elle fait partir, l'un après l'autre, les passages qui attendent leur tour (issue #211).

POURQUOI UNE FILE
Une nouvelle ville ajoutée par l'ETL demande un passage de la chaîne des services. Si un autre passage tourne déjà
(une seule recherche à la fois, verrou de MySQL), ou si le budget des agents est atteint, le passage n'est pas perdu :
il reste « en file » dans la table passages, et part dès que c'est possible. Deux villes ajoutées coup sur coup passent
ainsi l'une après l'autre, dans l'ordre où elles sont arrivées.

COMMENT
Un fil de fond, lancé au démarrage de l'API (start_worker), regarde la file toutes les minutes, et tout de suite quand
l'ETL vient d'y mettre une ville (wake). À chaque tour, il fait partir le plus ancien passage en file, si le verrou de
sa chaîne est libre et si le budget le permet ; sinon il attend le tour suivant. Le budget du lendemain, ou un budget
relevé par l'admin, est donc vu au plus tard une minute après.
La file est la table passages elle-même : après un redémarrage du serveur, les passages en file y sont toujours, et le
fil repart d'eux. Pas besoin d'un outil de plus (Celery, Redis) pour un passage à la fois.
"""
import threading

from services import passage_service, passage_store
from utils.logger_util import LoggerUtil

logger = LoggerUtil.get_logger("passages")

CHECK_SECONDS = 60          # le temps entre deux regards sur la file, quand personne ne la réveille

_wake = threading.Event()   # posé par wake() : le fil regarde la file sans attendre la fin de la minute
_worker = None              # le fil de fond, une fois lancé


def why_waiting(passage_id: str) -> str | None:
    """Pourquoi ce passage en file ne peut pas partir maintenant (verrou pris, budget atteint) ; None s'il peut partir."""
    return passage_service.waiting_reason(passage_store.load_passage(passage_id))


def run_next() -> bool:
    """
    Fait partir le plus ancien passage en file qui peut partir, et attend sa fin. Renvoie True s'il en a fait partir un
    (il y en a peut-être un autre derrière), False si la file est vide ou si tous doivent encore attendre.
    Un passage qui attend ne retient pas ceux d'après : un passage gratuit (OSM, carburants) part même quand un passage
    des services, plus ancien, attend le budget du lendemain.
    """
    for passage_id in passage_store.queued_ids():
        reason = why_waiting(passage_id)
        if reason:
            logger.info(f"[file] {passage_id} attend : {reason}")
            continue
        logger.info(f"[file] {passage_id} part")
        passage_service.run_passage(passage_id)
        return True
    return False


def work_forever() -> None:
    """
    Le travail du fil de fond : vider la file, puis attendre une minute ou un réveil, et recommencer. Une erreur (base
    injoignable un instant) est notée dans le journal et n'arrête pas le fil : il réessaie au tour suivant.
    """
    while True:
        try:
            while run_next():
                pass
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
