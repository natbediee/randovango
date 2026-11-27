"""Le département, la région et le pays d'une ville créée par une rando (issue #318)."""
from etl.load import load_gpx

CHAMPAGNE = {"name": "Champagne", "insee": "17083", "latitude": 45.9, "longitude": -0.9,
             "department": "Charente-Maritime", "region": "Nouvelle-Aquitaine"}


def test_a_new_city_takes_its_department_from_the_state(monkeypatch) -> None:
    """Une ville créée par une rando prend son département et sa région à l'État, sans Nominatim qui refusait l'import du 23 novembre."""
    monkeypatch.setattr(load_gpx, "get_commune_details", lambda insee: CHAMPAGNE)
    monkeypatch.setattr(load_gpx, "get_admin_info_from_coordinates", lambda *args: (None, None, None))
    assert load_gpx.find_admin_info("17083", 45.9, -0.9) == ("Charente-Maritime", "Nouvelle-Aquitaine", "France")


def test_a_start_without_commune_still_asks_nominatim(monkeypatch) -> None:
    """Un départ sans commune française (hors de France) garde le département et le pays donnés par Nominatim."""
    monkeypatch.setattr(load_gpx, "get_commune_details", lambda insee: CHAMPAGNE)
    monkeypatch.setattr(load_gpx, "get_admin_info_from_coordinates", lambda *args: ("Gipuzkoa", "Euskadi", "España"))
    assert load_gpx.find_admin_info(None, 43.3, -1.9) == ("Gipuzkoa", "Euskadi", "España")


def test_the_state_silent_falls_back_on_nominatim(monkeypatch) -> None:
    """Si l'État ne répond pas, même après ses essais, Nominatim donne ce qu'il peut plutôt que rien."""
    monkeypatch.setattr(load_gpx, "get_commune_details", lambda insee: None)
    monkeypatch.setattr(load_gpx, "get_admin_info_from_coordinates", lambda *args: ("Charente-Maritime", "Nouvelle-Aquitaine", "France"))
    assert load_gpx.find_admin_info("17083", 45.9, -0.9) == ("Charente-Maritime", "Nouvelle-Aquitaine", "France")


def test_a_commune_read_with_the_gpx_is_not_asked_again(monkeypatch) -> None:
    """Une ville nouvelle dont la lecture du GPX a déjà donné le département ne redemande pas l'État au chargement (envoi de 240 randos, 25 novembre 2026)."""
    def not_asked(insee):
        raise AssertionError("l'État ne devait pas être redemandé")
    monkeypatch.setattr(load_gpx, "get_commune_details", not_asked)
    assert load_gpx.find_admin_info("17083", 45.9, -0.9, CHAMPAGNE) == ("Charente-Maritime", "Nouvelle-Aquitaine", "France")


def test_a_commune_read_without_department_is_asked_again(monkeypatch) -> None:
    """Une commune lue sans département (réponse partielle de l'État) est redemandée au chargement, comme avant."""
    monkeypatch.setattr(load_gpx, "get_commune_details", lambda insee: CHAMPAGNE)
    partial = {"name": "Champagne", "insee": "17083", "department": None, "region": None}
    assert load_gpx.find_admin_info("17083", 45.9, -0.9, partial) == ("Charente-Maritime", "Nouvelle-Aquitaine", "France")
