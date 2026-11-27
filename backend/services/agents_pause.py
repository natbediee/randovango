"""
La pause des étapes payantes quand le fournisseur des agents refuse pour un temps (issue #332).

LE CAS RÉEL
Le 27 novembre 2026 vers 6 h 11, le quota des agents atteint, les services des villes 507 à 538 sont passés en échec
l'un après l'autre, en quelques secondes : chacun a buté sur la même limite. Un script local les reprenait ensuite
toutes les dix minutes.

CE QUI SE PASSE DÉSORMAIS
Le service d'accès au modèle (agents/llm_service.py), seul à connaître le fournisseur, traduit sa limite en une
erreur neutre, LLMLimitReached, avec l'heure à partir de laquelle réessayer. Une partie payante coupée par elle ne
passe pas en échec : elle retourne en file (passage_service), et la pause est notée ici jusqu'à cette heure. Pendant
la pause, les étapes payantes de la file attendent (passage_queue) ; les étapes gratuites continuent. L'heure passée,
la file reprend les passages arrêtés, du plus ancien au plus récent, sans repayer ce qui est fait.

Ce fichier ne sait rien du modèle qui tourne derrière : changer de fournisseur ne le touche pas.

La pause est gardée en mémoire, dans le programme qui fait tourner la file : après un redémarrage, le premier appel
payant retrouve la limite, et la pause est notée de nouveau.

L'heure de fin de la pause est une heure du serveur, en UTC comme la base, et se compare à datetime.now() : la pause
s'arrête donc au bon moment, été comme hiver. Seule la phrase lue par l'administratrice la donne à l'heure de Paris
(#299).
"""
from datetime import datetime

from utils.paris_time import to_paris

_until = None       # la fin de la pause en cours (heure du serveur, en UTC), ou None
_reason = None      # la raison de la pause, en phrase lisible


def pause(until: datetime, reason: str) -> None:
    """Note la pause des étapes payantes jusqu'à `until` ; une pause déjà plus longue est gardée."""
    global _until, _reason
    if _until is None or until > _until:
        _until, _reason = until, reason


def paused_reason(now: datetime | None = None) -> str | None:
    """
    Pourquoi les étapes payantes attendent, en phrase lisible, avec l'heure de reprise à l'heure de Paris ; None si la
    pause est finie, ou s'il n'y en a pas.
    """
    global _until, _reason
    now = now or datetime.now()
    if _until is None or now >= _until:
        _until, _reason = None, None
        return None
    return f"{_reason} : la file reprend seule vers {to_paris(_until):%H h %M}"


def clear() -> None:
    """Oublie la pause : pour les tests."""
    global _until, _reason
    _until, _reason = None, None
