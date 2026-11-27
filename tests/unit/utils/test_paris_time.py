"""
L'heure de Paris tirée des heures de la base, gardées en UTC (utils/paris_time.py, issue #299).

Les jours choisis encadrent les deux changements d'heure de 2026 : le dimanche 29 mars (UTC+1 devient UTC+2) et le
dimanche 25 octobre (UTC+2 redevient UTC+1).
"""
from datetime import date, datetime, timedelta

from utils.paris_time import paris_midnight, paris_today, to_paris


def test_a_winter_hour_is_one_hour_later_in_paris() -> None:
    """Un changement de réglage noté 10 h 49 en base, le 20 novembre, s'affiche 11 h 49 à Paris (cas vu pendant #211)."""
    shown = to_paris(datetime(2026, 11, 20, 10, 49))
    assert (shown.hour, shown.minute) == (11, 49)
    assert shown.utcoffset() == timedelta(hours=1)


def test_a_summer_hour_is_two_hours_later_in_paris() -> None:
    """Un appel d'agent noté 14 h en base, le 15 juillet, s'affiche 16 h à Paris : l'heure d'été ajoute une heure de plus."""
    shown = to_paris(datetime(2026, 7, 15, 14, 0))
    assert shown.hour == 16 and shown.utcoffset() == timedelta(hours=2)


def test_the_offset_follows_the_change_of_time_in_march() -> None:
    """Le 29 mars 2026, une heure notée 0 h 30 en base est 1 h 30 à Paris, et 1 h 30 en base est 3 h 30 : l'heure a sauté."""
    assert to_paris(datetime(2026, 3, 29, 0, 30)).hour == 1
    assert to_paris(datetime(2026, 3, 29, 1, 30)).hour == 3


def test_no_hour_stays_none() -> None:
    """Un passage pas encore commencé n'a pas d'heure de début : rien à convertir."""
    assert to_paris(None) is None


def test_the_paris_day_starts_at_midnight_in_paris() -> None:
    """À 23 h 30 en base le 27 novembre, il est 0 h 30 le 28 à Paris : c'est déjà le 28."""
    assert paris_today(datetime(2026, 11, 27, 23, 30)) == date(2026, 11, 28)
    assert paris_today(datetime(2026, 11, 27, 22, 59)) == date(2026, 11, 27)


def test_midnight_in_paris_is_23_h_utc_in_winter() -> None:
    """Minuit à Paris le 28 novembre, c'est 23 h le 27 en base : le plafond du jour repart à cette heure-là."""
    assert paris_midnight(date(2026, 11, 28)) == datetime(2026, 11, 27, 23, 0)


def test_midnight_in_paris_is_22_h_utc_in_summer() -> None:
    """Minuit à Paris le 15 juillet, c'est 22 h le 14 en base : l'heure d'été avance le début du jour d'une heure."""
    assert paris_midnight(date(2026, 7, 15)) == datetime(2026, 7, 14, 22, 0)


def test_midnight_follows_the_change_of_time_in_october() -> None:
    """Le 25 octobre 2026 commence à 22 h UTC la veille (été) ; le 26, à 23 h UTC la veille (hiver)."""
    assert paris_midnight(date(2026, 10, 25)) == datetime(2026, 10, 24, 22, 0)
    assert paris_midnight(date(2026, 10, 26)) == datetime(2026, 10, 25, 23, 0)
