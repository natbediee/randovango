"""Le rattrapage des villes sans commune, département ou région (issue #318)."""
from unittest.mock import MagicMock

from etl import fill_city_admin as script

CHAMPAGNE_DETAILS = {"name": "Champagne", "insee": "17083", "latitude": 45.9, "longitude": -0.9,
                     "department": "Charente-Maritime", "region": "Nouvelle-Aquitaine"}
JONCHERE_DETAILS = {"name": "La Jonchère", "insee": "85116", "latitude": 46.43, "longitude": -1.38,
                    "department": "Vendée", "region": "Pays de la Loire"}


def city(**columns) -> dict:
    """Une ligne de cities à compléter, sans rien d'autre que ce que le test précise."""
    return {"id": 1, "name": "?", "latitude": 46.0, "longitude": -1.0, "commune": None, "insee": None,
            "department": None, "region": None, "country": None, **columns}


def test_a_city_with_its_commune_gets_its_department_and_region(monkeypatch) -> None:
    """Champagne, qui avait déjà sa commune, reçoit la Charente-Maritime, la Nouvelle-Aquitaine et la France."""
    def not_asked(*args):
        raise AssertionError("la commune est déjà connue : sa position ne doit pas être demandée")
    monkeypatch.setattr(script, "get_commune_from_coordinates", not_asked)
    monkeypatch.setattr(script, "get_commune_details", lambda insee: CHAMPAGNE_DETAILS)
    assert script.find_admin(city(name="Champagne", commune="Champagne", insee="17083")) == {
        "commune": "Champagne", "insee": "17083", "department": "Charente-Maritime",
        "region": "Nouvelle-Aquitaine", "country": "France"}


def test_a_city_without_commune_finds_it_by_its_position(monkeypatch) -> None:
    """La Jonchère, restée sans code INSEE à l'import du 23 novembre, retrouve sa commune par la position de la ville."""
    monkeypatch.setattr(script, "get_commune_from_coordinates", lambda *args: ("La Jonchère", "85116"))
    monkeypatch.setattr(script, "get_commune_details", lambda insee: JONCHERE_DETAILS)
    assert script.find_admin(city(name="La Jonchère"))["insee"] == "85116"
    assert script.find_admin(city(name="La Jonchère"))["department"] == "Vendée"


def test_a_city_outside_france_is_left_as_it_is(monkeypatch) -> None:
    """Une ville qu'aucune commune française ne contient n'est pas complétée."""
    monkeypatch.setattr(script, "get_commune_from_coordinates", lambda *args: (None, None))
    assert script.find_admin(city(name="Hondarribia")) is None


def test_only_empty_columns_are_written() -> None:
    """Le rattrapage ne remplit que les colonnes vides : une commune ou un département déjà en base ne change pas."""
    cursor = MagicMock()
    script.write_admin(cursor, 261, {"commune": "Champagne", "insee": "17083", "department": "Charente-Maritime",
                                     "region": "Nouvelle-Aquitaine", "country": "France"})
    query = cursor.execute.call_args.args[0]
    for column in ("commune", "insee", "department", "region", "country"):
        assert f"{column} = COALESCE({column}, %s)" in query
