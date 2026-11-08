from utils import geo_utils
from utils.geo_utils import get_bounding_box


def test_get_bounding_box_orders_bounds() -> None:
    min_lat, min_lon, max_lat, max_lon = get_bounding_box(48.39, -4.49, 10)

    assert min_lat < max_lat
    assert min_lon < max_lon


def test_get_bounding_box_zero_distance_returns_same_point() -> None:
    min_lat, min_lon, max_lat, max_lon = get_bounding_box(48.39, -4.49, 0)

    assert min_lat == max_lat == 48.39
    assert min_lon == max_lon == -4.49


class FakeResponse:
    def __init__(self, features):
        self.features = features

    def raise_for_status(self):
        pass

    def json(self):
        return {"features": self.features}


def ban_feature(kind, score, lon=-4.704854, lat=48.345872):
    return {"properties": {"type": kind, "score": score}, "geometry": {"coordinates": [lon, lat]}}


def test_ban_returns_latitude_then_longitude_for_a_precise_address(monkeypatch) -> None:
    monkeypatch.setattr(geo_utils.requests, "get", lambda *a, **k: FakeResponse([ban_feature("housenumber", 0.95)]))
    assert geo_utils.geocode_address_ban("2 boulevard de la Mer, 29217 Plougonvelin") == (48.345872, -4.704854)


def test_ban_ignores_a_town_alone_or_a_doubtful_match(monkeypatch) -> None:
    monkeypatch.setattr(geo_utils.requests, "get", lambda *a, **k: FakeResponse([ban_feature("municipality", 0.9)]))
    assert geo_utils.geocode_address_ban("Plougonvelin") is None
    monkeypatch.setattr(geo_utils.requests, "get", lambda *a, **k: FakeResponse([ban_feature("street", 0.3)]))
    assert geo_utils.geocode_address_ban("rue inconnue") is None


def test_ban_down_never_blocks_the_caller(monkeypatch) -> None:
    def down(*args, **kwargs):
        raise geo_utils.requests.ConnectionError("injoignable")
    monkeypatch.setattr(geo_utils.requests, "get", down)
    assert geo_utils.geocode_address_ban("2 boulevard de la Mer") is None


def test_the_distance_to_a_trace_is_the_one_to_its_closest_point() -> None:
    from utils.geo_utils import distance_to_trace_km
    trace = [(48.30, -4.70), (48.31, -4.70), (48.32, -4.70)]
    assert distance_to_trace_km(48.31, -4.70, trace) == 0
    assert round(distance_to_trace_km(48.32, -4.69, trace), 2) == 0.74   # 0,01° de longitude
    assert distance_to_trace_km(48.31, -4.70, []) is None


class FakeCommunes:
    def __init__(self, rows):
        self.rows = rows

    def raise_for_status(self):
        pass

    def json(self):
        return self.rows


def test_the_commune_of_a_point_comes_with_its_insee_code(monkeypatch) -> None:
    monkeypatch.setattr(geo_utils.requests, "get", lambda *a, **k: FakeCommunes([{"nom": "Plouarzel", "code": "29177"}]))
    assert geo_utils.get_commune_from_coordinates(48.424, -4.76797) == ("Plouarzel", "29177")


def test_a_point_outside_france_has_no_commune(monkeypatch) -> None:
    monkeypatch.setattr(geo_utils.requests, "get", lambda *a, **k: FakeCommunes([]))
    assert geo_utils.get_commune_from_coordinates(50.0, -10.0) == (None, None)


def test_geo_api_down_never_blocks_the_caller(monkeypatch) -> None:
    def down(*args, **kwargs):
        raise geo_utils.requests.ConnectionError("injoignable")
    monkeypatch.setattr(geo_utils.requests, "get", down)
    assert geo_utils.get_commune_from_coordinates(48.424, -4.76797) == (None, None)


def test_a_city_is_searched_as_its_commune_once_known() -> None:
    assert geo_utils.city_commune({"name": "Trézien", "commune": "Plouarzel"}) == "Plouarzel"
    assert geo_utils.city_commune({"name": "Trézien", "commune": None}) == "Trézien"
