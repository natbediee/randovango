"""
Mapping code météo (OpenMeteo/ECMWF) -> nom de pictogramme (sans extension),
libellés en français et heure du coucher du soleil.
"""
from datetime import date, datetime, time, timedelta, timezone
from math import acos, cos, degrees, pi, radians, sin, tan
from zoneinfo import ZoneInfo

FRANCE = ZoneInfo("Europe/Paris")

# Libellé d'un picto, pour un texte (message envoyé à Vany par exemple).
PICTO_LABELS = {
    "sun": "ensoleillé",
    "partly_cloudy": "éclaircies",
    "cloud": "couvert",
    "fog": "brouillard",
    "rain": "pluie",
    "snow": "neige",
    "storm": "orage",
}

def meteo_code_to_picto(code):
    """
    Mapping Open-Meteo weather_code + temp_max vers le nom du picto (image).
    """
    if code in [0, 1]:
        return 'sun'
    elif code in [2]:
        return 'partly_cloudy'
    elif code in [3]:
        return 'cloud'
    elif code in [45, 48]:
        return 'fog'
    elif code in [51, 53, 55, 61, 63, 65, 80, 81, 82]:
        return 'rain'
    elif code in [71, 73, 75, 77, 85, 86]:
        return 'snow'
    elif code in [95, 96, 99]:
        return 'storm'
    else:
        return 'indisponible'


def sunset_time(day: date, latitude: float, longitude: float) -> time:
    """
    Heure locale (France) du coucher du soleil, à la minute près environ : formule
    de la NOAA (équation du temps et déclinaison du soleil selon le jour de l'année).
    Assez précis pour conseiller un point de vue « au coucher du soleil ».
    """
    gamma = 2 * pi / 365 * (day.timetuple().tm_yday - 1)
    equation_of_time = 229.18 * (0.000075 + 0.001868 * cos(gamma) - 0.032077 * sin(gamma)
                                 - 0.014615 * cos(2 * gamma) - 0.040849 * sin(2 * gamma))
    declination = (0.006918 - 0.399912 * cos(gamma) + 0.070257 * sin(gamma) - 0.006758 * cos(2 * gamma)
                   + 0.000907 * sin(2 * gamma) - 0.002697 * cos(3 * gamma) + 0.00148 * sin(3 * gamma))
    lat = radians(latitude)
    hour_angle = degrees(acos(cos(radians(90.833)) / (cos(lat) * cos(declination)) - tan(lat) * tan(declination)))
    minutes_utc = 720 - 4 * (longitude - hour_angle) - equation_of_time
    sunset_utc = datetime.combine(day, time(0), tzinfo=timezone.utc) + timedelta(minutes=minutes_utc)
    return sunset_utc.astimezone(FRANCE).time().replace(second=0, microsecond=0)
