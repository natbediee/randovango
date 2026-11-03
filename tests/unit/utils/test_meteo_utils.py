from datetime import date, time

from utils.meteo_utils import meteo_code_to_picto, sunset_time


def test_meteo_code_to_picto_known_values() -> None:
    assert meteo_code_to_picto(0) == "sun"
    assert meteo_code_to_picto(2) == "partly_cloudy"
    assert meteo_code_to_picto(3) == "cloud"
    assert meteo_code_to_picto(45) == "fog"
    assert meteo_code_to_picto(63) == "rain"
    assert meteo_code_to_picto(71) == "snow"
    assert meteo_code_to_picto(95) == "storm"


def test_meteo_code_to_picto_unknown_value() -> None:
    assert meteo_code_to_picto(999) == "indisponible"


def test_sunset_time_in_local_time_summer_and_winter() -> None:
    # Brest : vers 18 h début novembre (heure d'hiver), vers 22 h 20 fin juin (heure d'été).
    assert time(17, 50) <= sunset_time(date(2026, 11, 1), 48.39, -4.49) <= time(18, 10)
    assert time(22, 10) <= sunset_time(date(2026, 6, 21), 48.39, -4.49) <= time(22, 30)


def test_the_sun_sets_later_in_the_west() -> None:
    # Paris est 6,8° plus à l'est que Brest : environ 27 min plus tôt (4 min par degré).
    brest = sunset_time(date(2026, 11, 1), 48.39, -4.49)
    paris = sunset_time(date(2026, 11, 1), 48.85, 2.35)
    minutes = (brest.hour * 60 + brest.minute) - (paris.hour * 60 + paris.minute)
    assert 20 <= minutes <= 35
