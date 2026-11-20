"""
Les chaînes gratuites de l'ajout d'une ville (services/etl_chains.py, issue #276) : chaque partie rend ce qu'elle a
chargé, ou lève un échec avec une raison lisible ; le verrou d'une chaîne sur une ville est demandé à MySQL.
Ni réseau ni base : les étapes de l'ETL et la connexion à MySQL sont remplacées.
"""
from unittest.mock import MagicMock

import pytest

from agents.find_services import PassageRunning
from services import etl_chains
from services.etl_chains import StepFailed

GUIDEL = {"id": 12, "name": "Guidel"}


@pytest.mark.parametrize("run_part,etl_name,summary", [
    (etl_chains.run_osm, "run_osm_etl", {"lieux": 42}),
    (etl_chains.run_finess, "run_pharmacy_etl", {"pharmacies": 42}),
    (etl_chains.run_fuel, "run_fuel_etl", {"stations": 42}),
])
def test_each_free_chain_loads_the_city_and_gives_its_count(monkeypatch, run_part, etl_name, summary):
    """OSM, FINESS et les carburants chargent la ville par son nom et rendent en bilan le nombre de lieux chargés."""
    asked = []
    monkeypatch.setattr(etl_chains, etl_name, lambda name: asked.append(name) or 42)
    assert run_part("p1", "x", GUIDEL, False, lambda: None) == summary
    assert asked == ["Guidel"]


@pytest.mark.parametrize("run_part,etl_name,reason", [
    (etl_chains.run_osm, "run_osm_etl", "OpenStreetMap n'a pas répondu"),
    (etl_chains.run_finess, "run_pharmacy_etl", "fichier FINESS illisible"),
    (etl_chains.run_fuel, "run_fuel_etl", "fichier des prix des carburants"),
])
def test_a_free_chain_that_loads_nothing_fails_with_a_readable_reason(monkeypatch, run_part, etl_name, reason):
    """Une étape qui ne peut rien lire (Saint-Philibert sans réponse d'OSM) devient un échec avec sa raison, pas un silence."""
    monkeypatch.setattr(etl_chains, etl_name, lambda name: None)
    with pytest.raises(StepFailed, match=reason):
        run_part("p1", "x", GUIDEL, False, lambda: None)


@pytest.fixture
def mysql(monkeypatch):
    """Une connexion MySQL factice : `answer` est la réponse de GET_LOCK ou IS_FREE_LOCK (1 : obtenu ou libre)."""
    cursor = MagicMock()
    connection = MagicMock()
    connection.cursor.return_value = cursor
    monkeypatch.setattr(etl_chains.MySQLUtils, "connect", lambda: connection)
    monkeypatch.setattr(etl_chains.MySQLUtils, "disconnect", lambda conn: None)
    return cursor


def test_the_lock_is_taken_per_chain_and_city_then_released(mysql):
    """Le verrou porte le nom de la chaîne et de la ville, et se libère à la fin du passage."""
    mysql.fetchone.return_value = (1,)
    with etl_chains.city_lock("osm", 12):
        pass
    sql = [call.args for call in mysql.execute.call_args_list]
    assert sql == [("SELECT GET_LOCK(%s, 0)", ("randovango_osm_12",)), ("SELECT RELEASE_LOCK(%s)", ("randovango_osm_12",))]


def test_a_lock_already_held_leaves_the_passage_in_the_queue(mysql):
    """La même chaîne déjà lancée sur la même ville : PassageRunning, qui laisse le passage en file au lieu d'un échec."""
    mysql.fetchone.return_value = (0,)
    with pytest.raises(PassageRunning):
        with etl_chains.city_lock("osm", 12):
            pass
    mysql.fetchone.return_value = (0,)
    assert etl_chains.city_lock_is_free("osm", 12) is False
