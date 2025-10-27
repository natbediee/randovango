"""
Mapping code météo (OpenMeteo/ECMWF) -> nom de pictogramme (sans extension)
"""

def meteo_code_to_picto(code: int) -> str:
    # Mapping minimal basé sur les fichiers présents
    if code in (0, 1):
        return "sun"
    if code in (2, 3, 45, 48):
        return "cloud"
    if code in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82):
        return "rain"
    if code in (71, 73, 75, 77, 85, 86):
        return "cloud"  # Pas de snow, fallback cloud
    if code in (95, 96, 99):
        return "storm"
    if code in (45, 48):
        return "fog"
    return "indispo"
