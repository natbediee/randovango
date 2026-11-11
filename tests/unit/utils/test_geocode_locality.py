from services import service_store
from utils import geo_utils


class _Response:
    def __init__(self, features):
        self.features = features

    def raise_for_status(self):
        pass

    def json(self):
        return {"features": self.features}


def _feature(kind, score, longitude=-4.7207, latitude=48.3521):
    return {"properties": {"type": kind, "score": score}, "geometry": {"coordinates": [longitude, latitude]}}


def test_a_hamlet_is_found_without_the_word_lieu_dit(monkeypatch):
    asked = []
    monkeypatch.setattr(geo_utils.requests, "get", lambda url, params, timeout: asked.append(params) or _Response([_feature("locality", 0.95)]))
    assert geo_utils.geocode_locality_ban("Lieu-dit Le Lannou, 29217 Plougonvelin") == (48.3521, -4.7207)
    assert asked[0]["q"] == "Le Lannou, 29217 Plougonvelin" and asked[0]["type"] == "locality"


def test_a_weak_hamlet_is_refused(monkeypatch):
    monkeypatch.setattr(geo_utils.requests, "get", lambda url, params, timeout: _Response([_feature("locality", 0.6)]))
    assert geo_utils.geocode_locality_ban("Kerhor, 29700 Pluguffan") is None


def test_the_place_takes_the_hamlet_when_the_street_is_unknown(monkeypatch):
    monkeypatch.setattr(service_store, "geocode_address_ban", lambda address, latitude, longitude: None)
    monkeypatch.setattr(service_store, "geocode_locality_ban", lambda address, latitude, longitude: (48.3521, -4.7207))
    city = {"latitude": 48.3378, "longitude": -4.70183}
    assert service_store._position(city, "Lieu-dit Le Lannou, 29217 Plougonvelin") == (48.3521, -4.7207)
    monkeypatch.setattr(service_store, "geocode_locality_ban", lambda address, latitude, longitude: (43.2, 5.4))
    assert service_store._position(city, "Le Lannou") is None
