def transform_meteo_code(code):
    """
    Simplifie le weather_code Open-Meteo et retourne uniquement le nom du picto (image).
    """
    if code in [0, 1]:
        picto = 'sun.png'
    elif code in [2, 3]:
        picto = 'cloud.png'
    elif code in [45, 48]:
        picto = 'fog.png'
    elif code in [51, 53, 55, 61, 63, 65, 80, 81, 82]:
        picto = 'rain.png'
    elif code in [71, 73, 75, 77, 85, 86]:
        picto = 'snow.png'
    elif code in [95, 96, 99]:
        picto = 'storm.png'
    else:
        picto = 'indispo.png'
    return {
        'picto': picto
    }
