"""
Mapping code météo (OpenMeteo/ECMWF) -> nom de pictogramme (sans extension)
"""

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