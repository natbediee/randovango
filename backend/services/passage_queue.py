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

COMMENT
Un fil de fond, lancé au démarrage de l'API (start_worker), regarde la file toutes les minutes, et tout de suite quand
l'ETL vient d'y mettre une ville (wake). À chaque tour, il fait partir le premier passage en file, si le verrou de
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

# L'ordre dans lequel la file fait passer les chaînes : les gratuites et rapides d'abord, les services en dernier.
CHAIN_ORDER = ("osm", "carburants", "finess", "spots", "pepites", "services")

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
