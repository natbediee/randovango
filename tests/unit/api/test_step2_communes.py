"""
Étape 2 : depuis une commune, les randos de ses lieux-dits restent proposées, même loin de son centre (issue #184).
Cas réel : la rando de Locuon, « Les sources de l'Aër », part à 6 km du centre de Ploërdut ; depuis que « Où pars-tu »
ne propose plus Locuon, elle n'était plus proposée nulle part.
"""
from api.routers import step2
from utils.geo_utils import SAME_COMMUNE_HIKES

PLOERDUT = {"latitude": 48.0979, "longitude": -3.2802, "insee": "56163"}
LOCUON_HIKE = {"id": 173, "name": "Les sources de l'Aër", "difficulte": "Facile", "duration": 3.0, "distance_km": 10.0,
               "start_latitude": 48.1502, "start_longitude": -3.3037, "elevation_gain_m": 120, "verifie": 1,
               "description": None, "city_id": 125}


class _Cursor:
    """Faux curseur : la ville choisie est Ploërdut, la base ne connaît que la rando de Locuon ; il note la requête."""

    def __init__(self):
        self.queries = []

    def execute(self, sql, params=None):
        self.queries.append((sql, params))

    def fetchone(self):
        return dict(PLOERDUT)

    def fetchall(self):
        return [dict(LOCUON_HIKE)]

    def close(self):
        pass


def test_the_hikes_of_a_locality_are_offered_from_its_commune(monkeypatch) -> None:
    """Depuis Ploërdut, l'étape 2 cherche aussi les randos rangées dans une ville de la même commune : celle de Locuon."""
    cursor = _Cursor()
    connection = type("Connection", (), {"cursor": lambda self, dictionary=False: cursor})()
    monkeypatch.setattr(step2.MySQLUtils, "connect", staticmethod(lambda: connection))
    monkeypatch.setattr(step2.MySQLUtils, "disconnect", staticmethod(lambda cnx: None))

    hikes = step2.get_hikes(city_id=147, distance_km=5)

    query, params = cursor.queries[-1]
    assert f"OR {SAME_COMMUNE_HIKES}" in query and params[-1] == "56163"
    assert [hike["name"] for hike in hikes] == ["Les sources de l'Aër"]
