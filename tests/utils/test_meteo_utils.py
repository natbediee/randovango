from utils.meteo_utils import meteo_code_to_picto


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
