from api.routers import step4


def _row(poi_id, name, category, genre, address, latitude=48.34):
    return {"id": poi_id, "name": name, "description": None, "latitude": latitude, "longitude": -4.70, "verifie": 1, "image_url": None,
            "url": None, "address": address, "service_category": category, "service_name": category, "genre": genre, "pourquoi": None,
            "budget": None, "jours_fermeture": None, "distinction": None, "statut_saison": None, "mois_ouverture": None}


class _Cursor:
    def __init__(self, rows):
        self.rows, self.params = rows, None

    def execute(self, sql, params=None):
        if "FROM poi" in sql:
            self.sql, self.params = sql, params

    def fetchone(self):
        return {"name": "Plougonvelin", "latitude": 48.3378, "longitude": -4.70183}

    def fetchall(self):
        return self.rows

    def close(self):
        pass


def _get_poi(monkeypatch, rows):
    cursor = _Cursor(rows)
    connection = type("Connection", (), {"cursor": lambda self, dictionary=False: cursor})()
    monkeypatch.setattr(step4.MySQLUtils, "connect", staticmethod(lambda: connection))
    monkeypatch.setattr(step4.MySQLUtils, "disconnect", staticmethod(lambda connection: None))
    return step4.get_poi(city_id=2, distance_km=5, spot_lat=None, spot_lon=None), cursor


def test_a_sheet_of_the_commune_beyond_the_zone_is_asked_for(monkeypatch):
    _, cursor = _get_poi(monkeypatch, [])
    assert cursor.params[-1] == "%Plougonvelin" and "p.address LIKE" in cursor.sql


def test_the_commune_sheets_are_not_pushed_out_by_nearer_places(monkeypatch):
    far_sheets = [_row(number, f"Fiche {number}", "restaurant", "x", "7 place, 29217 Plougonvelin", latitude=48.38) for number in range(10)]
    cafe = _row(100, "Café tout proche", "cafe", None, "1 rue, 29217 Plougonvelin")
    result, _ = _get_poi(monkeypatch, [cafe, *far_sheets])
    names = [poi["name"] for poi in result["restauration"]]
    assert len(names) == 10 and "Café tout proche" not in names


def test_a_commune_not_treated_keeps_its_own_restaurants(monkeypatch):
    rows = [_row(1, "La Cabane", "restaurant", "x", "1 bd, 29217 Plougonvelin"), _row(2, "La Cormorandière", "restaurant", None, "Place, 29280 Locmaria-Plouzané")]
    result, _ = _get_poi(monkeypatch, rows)
    assert {poi["name"] for poi in result["restauration"]} == {"La Cabane", "La Cormorandière"}
