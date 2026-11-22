"""
La chaîne des pépites d'une ville (services/pepite_chain.py, issue #276) : la recherche des lieux autour de la ville,
avec son bilan ; une zone déjà couverte ne coûte rien ; l'erreur de Vany remonte au passage.
Ni base ni agent : la connexion et les recherches sont remplacées.
"""
from unittest.mock import MagicMock

import pytest

from agents.llm_service import LLMUnavailable
from services import pepite_chain, pepite_service

GUIDEL = {"id": 12, "name": "Guidel", "latitude": 47.79, "longitude": -3.49}


@pytest.fixture
def city(monkeypatch):
    """La base remplacée : la ville Guidel est trouvée par son id ; `state` dit si sa zone est déjà couverte."""
    state = {"covered": False, "relocated": []}
    cursor = MagicMock()
    cursor.fetchone.return_value = GUIDEL
    connection = MagicMock()
    connection.cursor.return_value = cursor
    monkeypatch.setattr(pepite_service.MySQLUtils, "connect", lambda: connection)
    monkeypatch.setattr(pepite_service.MySQLUtils, "disconnect", lambda conn: None)
    monkeypatch.setattr(pepite_service, "_places_covered", lambda cursor, city: state["covered"])
    monkeypatch.setattr(pepite_service, "_city_context", lambda cursor, city: {"city_name": city["name"]})
    monkeypatch.setattr(pepite_service, "relocate_zone", lambda cursor, zone: state["relocated"].append(zone))
    return state


def test_the_places_of_a_city_are_searched_and_counted(city, monkeypatch):
    """Vany cherche les lieux autour de Guidel, les place, et le bilan dit combien de pépites ont été trouvées."""
    asked = []

    def search(cursor, zone, mode, trip_day_id=None, raise_errors=False):
        asked.append((zone["city_name"], mode, raise_errors))
        return 12
    monkeypatch.setattr(pepite_service, "search_and_store", search)
    assert pepite_chain.run_part("p1", "lieux", GUIDEL, False, lambda: None) == {"pepites_trouvees": 12}
    assert asked == [("Guidel", "lieux", True)] and city["relocated"] == [{"city_name": "Guidel"}]


def test_a_zone_already_covered_costs_nothing(city, monkeypatch):
    """Une zone qu'une recherche récente couvre déjà n'est pas recherchée : relancer la ville ne coûte rien."""
    city["covered"] = True
    monkeypatch.setattr(pepite_service, "search_and_store", lambda *args, **kwargs: pytest.fail("aucune recherche"))
    assert pepite_chain.run_part("p1", "lieux", GUIDEL, False, lambda: None) == {
        "pepites_trouvees": 0, "zones_deja_couvertes": 1}


def test_an_error_of_vany_goes_up_to_the_passage(city, monkeypatch):
    """Vany sans réponse (quota) : l'erreur remonte, le passage la garde comme raison de son échec au lieu de se dire fini."""
    def search(cursor, zone, mode, trip_day_id=None, raise_errors=False):
        raise LLMUnavailable("You've hit your session limit · resets 1:40pm (UTC)")
    monkeypatch.setattr(pepite_service, "search_and_store", search)
    with pytest.raises(LLMUnavailable):
        pepite_chain.run_part("p1", "lieux", GUIDEL, False, lambda: None)


def test_the_search_keeps_logging_its_error_outside_the_chain(monkeypatch):
    """Hors de la chaîne (un voyage), une recherche ratée est écrite dans le journal et rend None, comme avant."""
    monkeypatch.setattr(pepite_service, "find_candidates", lambda cursor, day: [])

    def broken(day, known_names):
        raise LLMUnavailable("Error code: 529 overloaded_error")
    monkeypatch.setattr("agents.discover_places.search_places", broken)
    assert pepite_service.search_and_store(MagicMock(), {"city_name": "Guidel"}, "lieux") is None
    with pytest.raises(LLMUnavailable):
        pepite_service.search_and_store(MagicMock(), {"city_name": "Guidel"}, "lieux", raise_errors=True)
