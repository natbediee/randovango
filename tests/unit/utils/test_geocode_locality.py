from services import service_store
from utils import geo_utils


class _Response:
    def __init__(self, features):
        self.features = features

    def raise_for_status(self):
        pass

    def json(self):
        return {"features": self.features}


def _feature(kind, score, longitude=-4.7207, latitude=48.3521, name=None):
    return {"properties": {"type": kind, "score": score, "name": name}, "geometry": {"coordinates": [longitude, latitude]}}


def test_a_hamlet_is_found_without_the_word_lieu_dit(monkeypatch):
    """Un lieu-dit est cherché sans le mot « Lieu-dit », qui fait chuter le score de la Base Adresse (Le Lannou, à Plougonvelin)."""
    asked = []
    monkeypatch.setattr(geo_utils.requests, "get", lambda url, params, timeout: asked.append(params) or _Response([_feature("locality", 0.95)]))
    assert geo_utils.geocode_locality_ban("Lieu-dit Le Lannou, 29217 Plougonvelin") == (48.3521, -4.7207)
    assert asked[0]["q"] == "Le Lannou, 29217 Plougonvelin" and asked[0]["type"] == "locality"


def test_a_weak_hamlet_is_refused(monkeypatch):
    """Un lieu-dit reconnu avec un score trop faible est refusé (Kerhor, à Pluguffan)."""
    monkeypatch.setattr(geo_utils.requests, "get", lambda url, params, timeout: _Response([_feature("locality", 0.6)]))
    assert geo_utils.geocode_locality_ban("Kerhor, 29700 Pluguffan") is None


def test_the_place_takes_the_hamlet_when_the_street_is_unknown(monkeypatch):
    """Sans rue reconnue, le service prend la position de son lieu-dit (Le Lannou, à Plougonvelin), sauf s'il est loin de la commune."""
    monkeypatch.setattr(service_store, "geocode_address_ban", lambda address, latitude, longitude: None)
    monkeypatch.setattr(service_store, "geocode_locality_ban", lambda address, latitude, longitude: (48.3521, -4.7207))
    monkeypatch.setattr(service_store, "geocode_way_ban", lambda address, latitude, longitude: None)
    city = {"latitude": 48.3378, "longitude": -4.70183}
    assert service_store._position(city, "Lieu-dit Le Lannou, 29217 Plougonvelin") == (48.3521, -4.7207)
    monkeypatch.setattr(service_store, "geocode_locality_ban", lambda address, latitude, longitude: (43.2, 5.4))
    assert service_store._position(city, "Le Lannou") is None


def test_a_hamlet_slipped_in_the_address_is_left_out_on_a_second_try(monkeypatch):
    """« 10 route de Crozon, Tal ar Groas, 29160 Crozon » est placée au second essai, sans « Tal ar Groas », par la recherche sûre."""
    asked = []

    def sure(address, latitude, longitude):
        asked.append(address)
        return (48.2470, -4.4310)

    monkeypatch.setattr(service_store, "geocode_address_ban", lambda address, latitude, longitude: None)
    monkeypatch.setattr(service_store, "geocode_locality_ban", lambda address, latitude, longitude: None)
    monkeypatch.setattr(service_store, "geocode_sure_address_ban", sure)
    monkeypatch.setattr(service_store, "geocode_way_ban", lambda address, latitude, longitude: None)
    city = {"latitude": 48.2460, "longitude": -4.4890}
    assert service_store._position(city, "10 route de Crozon, Tal ar Groas, 29160 Crozon") == (48.2470, -4.4310)
    assert asked == ["10 route de Crozon, 29160 Crozon"]
    assert service_store.without_locality("Bourg de Lampaul, 29242 Ouessant") is None


def test_the_second_try_needs_a_sure_answer(monkeypatch):
    """Au second essai, une réponse peu sûre est refusée : « Halles Saint-Martin » ne devient pas « rue des Halles Saint-Louis »."""
    monkeypatch.setattr(geo_utils.requests, "get", lambda url, params, timeout: _Response([_feature("street", 0.53)]))
    assert geo_utils.geocode_address_ban("Halles Saint-Martin, 29200 Brest") == (48.3521, -4.7207)
    assert geo_utils.geocode_sure_address_ban("Halles Saint-Martin, 29200 Brest") is None


def test_a_street_filed_as_a_hamlet_is_accepted_with_its_number(monkeypatch):
    """« 6 rue Jacques Rueff, 56000 Vannes », rangée en lieu-dit par la Base Adresse, est acceptée ; un vrai lieu-dit ou une adresse sans numéro ne le sont pas."""
    way = _Response([_feature("locality", 0.83, name="Rue Jacques Rueff")])
    monkeypatch.setattr(geo_utils.requests, "get", lambda url, params, timeout: way)
    assert geo_utils.geocode_way_ban("6 rue Jacques Rueff, 56000 Vannes") == (48.3521, -4.7207)
    assert geo_utils.geocode_way_ban("Rue Jacques Rueff, 56000 Vannes") is None
    hamlet = _Response([_feature("locality", 0.9, name="Tal-Ar-Groas")])
    monkeypatch.setattr(geo_utils.requests, "get", lambda url, params, timeout: hamlet)
    assert geo_utils.geocode_way_ban("10 route de Crozon, Tal ar Groas, 29160 Crozon") is None
