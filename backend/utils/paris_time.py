"""
L'heure de Paris pour ce que lit l'administratrice, à partir des heures gardées en base (issue #299).

LA RÈGLE
Les conteneurs du backend et de MySQL tournent en UTC : `datetime.now()` et `NOW()` y donnent l'heure UTC, et toutes
les heures de la base (llm_calls.called_at, passages.requested_at, agent_settings.changed_at…) sont donc en UTC, sans
fuseau. On les garde ainsi : les anciennes et les nouvelles lignes restent comparables, quelle que soit la branche
qui les écrit. Seul ce qu'une personne lit passe à l'heure de Paris, ici, au moment de le montrer.

Pour lire la base à la main à l'heure de Paris : CONVERT_TZ(called_at, 'UTC', 'Europe/Paris').

L'HEURE D'ÉTÉ
Paris est à UTC+1 l'hiver et à UTC+2 l'été ; ZoneInfo connaît les dates de changement, année par année. Minuit existe
toujours, une seule fois, à Paris : le changement d'heure se fait vers 2 h ou 3 h du matin.
"""
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

PARIS = ZoneInfo("Europe/Paris")
BASE_ZONE = timezone.utc     # le fuseau des heures de la base et des conteneurs


def to_paris(moment: datetime | None) -> datetime | None:
    """
    Une heure de la base (UTC, sans fuseau) en heure de Paris, avec son fuseau : 16 h 50 en novembre devient
    17 h 50 (+01:00). None reste None, pour un passage pas encore commencé.
    """
    if moment is None:
        return None
    return moment.replace(tzinfo=BASE_ZONE).astimezone(PARIS)


def paris_today(now: datetime) -> date:
    """Le jour qu'il est à Paris à cette heure de la base : le 28 dès minuit à Paris, même s'il est 23 h en UTC."""
    return to_paris(now).date()


def paris_midnight(day: date) -> datetime:
    """Minuit à Paris ce jour-là, en heure de la base (UTC, sans fuseau), pour comparer aux heures enregistrées."""
    midnight = datetime.combine(day, time(0), tzinfo=PARIS)
    return midnight.astimezone(BASE_ZONE).replace(tzinfo=None)
