"""
Le fichier du front, puis le dossier d'attente (etl_pipeline, issues #316 et #328) : le fichier envoyé par la page
d'ajout passe avant ceux d'un envoi en masse ; chaque ville reçoit sa météo, puis ses chaînes demandées à la file des
passages, sans retenir la réponse ; une erreur sur une chaîne, une ville ou un fichier n'arrête jamais les autres.
Ni réseau ni base : la lecture, le chargement, les demandes de passage et la météo sont remplacés.
"""
import threading
from unittest.mock import MagicMock

import pytest

from etl import etl_pipeline
from services import passage_queue, passage_service


@pytest.fixture
def asked(monkeypatch):
    """Ce que l'ETL demande à la file, dans l'ordre : les chaînes de la ville, les services, puis le réveil de la file."""
    calls = []
    monkeypatch.setattr(etl_pipeline, "logger", MagicMock())
    monkeypatch.setattr(passage_service, "request_city_chain", lambda key, city: calls.append((key, city)) or "p1")
    monkeypatch.setattr(passage_service, "request_etl_passage", lambda city: calls.append(("services", city)) or None)
    monkeypatch.setattr(passage_queue, "wake", lambda: calls.append(("réveil",)))
    return calls


def test_a_new_city_asks_each_of_its_chains_then_wakes_the_queue(asked) -> None:
    """Une ville ajoutée demande OSM, carburants, FINESS, spots, pépites et services à la file, puis la réveille, sans geste de l'administratrice."""
    etl_pipeline.request_city_chains("Plougonvelin")
    assert asked == [("osm", "Plougonvelin"), ("carburants", "Plougonvelin"), ("finess", "Plougonvelin"),
                     ("spots", "Plougonvelin"), ("pepites", "Plougonvelin"), ("services", "Plougonvelin"),
                     ("réveil",)]


def test_an_error_on_one_chain_never_stops_the_others(asked, monkeypatch) -> None:
    """Une base injoignable en demandant FINESS est notée dans le journal ; les spots, les pépites et les services sont quand même demandés."""
    def broken_on_finess(key, city):
        if key == "finess":
            raise ConnectionError("base injoignable")
        asked.append((key, city))
    monkeypatch.setattr(passage_service, "request_city_chain", broken_on_finess)
    etl_pipeline.request_city_chains("Saint-Philibert")
    assert ("spots", "Saint-Philibert") in asked and ("services", "Saint-Philibert") in asked
    assert any("finess non demandée pour Saint-Philibert" in call.args[0]
               for call in etl_pipeline.logger.warning.call_args_list)


def loaded(fname, city) -> dict:
    """Le résultat d'un fichier chargé sur cette ville, comme le rend process_file."""
    return {"filename": fname, "city": city, "reason": None}


def test_an_upload_answers_before_the_chains_are_asked(monkeypatch) -> None:
    """Le fichier du front rend sa ville après la météo, sans attendre la demande des chaînes (≈ 1 s par ville le 25 novembre 2026), qui se fait à côté."""
    may_ask, asked = threading.Event(), threading.Event()

    def slow_request(city):
        may_ask.wait(5)
        asked.set()
    monkeypatch.setattr(etl_pipeline, "process_file", lambda path, fname, verifie: loaded(fname, "Plougonvelin"))
    monkeypatch.setattr(etl_pipeline, "load_weather", lambda city: None)
    monkeypatch.setattr(etl_pipeline, "start_folder_worker", lambda role: None)
    monkeypatch.setattr(etl_pipeline, "request_city_chains", slow_request)

    outcome = etl_pipeline.process_upload("/usr/src/data/envoi/trace.gpx", user_role="admin")

    assert outcome["city"] == "Plougonvelin"
    assert not asked.is_set()
    may_ask.set()
    assert asked.wait(5)


def test_the_front_file_passes_before_the_waiting_folder(monkeypatch) -> None:
    """Pendant qu'un envoi en masse attend geo.api.gouv.fr pour un fichier du dossier, le fichier du front est chargé et répond sans l'attendre."""
    folder_may_go = threading.Event()

    def read_and_load(path, fname, verifie):
        if fname.startswith("dossier"):
            folder_may_go.wait(5)
        return loaded(fname, "Le Conquet")
    monkeypatch.setattr(etl_pipeline, "process_file", read_and_load)
    monkeypatch.setattr(etl_pipeline, "load_weather", lambda city: None)
    monkeypatch.setattr(etl_pipeline, "request_city_chains", lambda city: None)
    monkeypatch.setattr(etl_pipeline.gpx, "waiting_files", lambda: ["dossier-1.gpx", "dossier-2.gpx"])
    folder = threading.Thread(target=etl_pipeline.process_waiting_folder)
    folder.start()

    outcome = etl_pipeline.process_upload("/usr/src/data/envoi/front.gpx")

    assert outcome == loaded("front.gpx", "Le Conquet")
    assert folder.is_alive()
    folder_may_go.set()
    folder.join(5)


def test_each_city_of_the_folder_gets_its_weather_once_then_its_chains(monkeypatch) -> None:
    """Trois randos du dossier sur deux villes : chaque ville reçoit sa météo puis ses chaînes une seule fois, Le Conquet avant Plouarzel comme à l'arrivée."""
    weather, chains = [], []
    results = {"a.gpx": loaded("a.gpx", "Le Conquet"),
               "b.gpx": {"filename": "b.gpx", "city": None, "reason": "le fichier ne contient aucune trace"},
               "c.gpx": loaded("c.gpx", "Plouarzel"), "d.gpx": loaded("d.gpx", "Le Conquet")}
    monkeypatch.setattr(etl_pipeline.gpx, "waiting_files", lambda: sorted(results))
    monkeypatch.setattr(etl_pipeline, "process_waiting_file", lambda fname, verifie: results[fname])
    monkeypatch.setattr(etl_pipeline, "load_weather", weather.append)
    monkeypatch.setattr(etl_pipeline, "request_city_chains", chains.append)

    outcomes = etl_pipeline.process_waiting_folder()

    assert [outcome["filename"] for outcome in outcomes] == ["a.gpx", "b.gpx", "c.gpx", "d.gpx"]
    assert weather == chains == ["Le Conquet", "Plouarzel"]


def test_a_file_that_stays_in_the_folder_is_tried_only_once(monkeypatch) -> None:
    """Un fichier que le pipeline n'arrive pas à retirer du dossier n'est essayé qu'une fois : le fil de fond ne tourne pas sans fin."""
    tried = []
    monkeypatch.setattr(etl_pipeline.gpx, "waiting_files", lambda: ["coince.gpx"])
    monkeypatch.setattr(etl_pipeline, "process_waiting_file",
                        lambda fname, verifie: tried.append(fname) or {"filename": fname, "city": None, "reason": "erreur"})

    etl_pipeline.process_waiting_folder()

    assert tried == ["coince.gpx"]


def test_an_unexpected_error_on_a_folder_file_becomes_a_refusal(monkeypatch) -> None:
    """Une erreur inattendue sur un fichier du dossier (base injoignable à la lecture) devient un refus, et le fil passe au fichier suivant."""
    def broken(path, fname, verifie):
        raise ConnectionError("base injoignable")
    monkeypatch.setattr(etl_pipeline, "process_file", broken)

    assert etl_pipeline.process_waiting_file("trace.gpx", verifie=1)["reason"] == etl_pipeline.LOAD_FAILED


def test_only_one_thread_empties_the_folder(monkeypatch) -> None:
    """Pendant qu'un fil vide le dossier d'attente, un second envoi n'en lance pas un autre : le même fichier n'est jamais lu deux fois."""
    monkeypatch.setattr(etl_pipeline.gpx, "waiting_files", lambda: ["trace.gpx"])
    monkeypatch.setattr(etl_pipeline, "process_waiting_file", lambda fname, verifie: pytest.fail("fichier lu deux fois"))

    with etl_pipeline._folder_lock:
        assert etl_pipeline.process_waiting_folder() == []


def test_an_error_on_one_city_never_stops_the_next_ones(monkeypatch) -> None:
    """Une ville dont la demande échoue (base injoignable) est notée dans le journal ; la ville suivante est quand même demandée."""
    monkeypatch.setattr(etl_pipeline, "logger", MagicMock())
    asked = []

    def broken_on_crozon(city):
        if city == "Crozon":
            raise ConnectionError("base injoignable")
        asked.append(city)
    monkeypatch.setattr(etl_pipeline, "request_city_chains", broken_on_crozon)

    etl_pipeline.request_chains_of_cities(["Crozon", "Camaret-sur-Mer"])

    assert asked == ["Camaret-sur-Mer"]
    assert any("Chaînes non demandées pour Crozon" in call.args[0]
               for call in etl_pipeline.logger.warning.call_args_list)


def test_two_uploads_never_ask_their_chains_at_the_same_time(monkeypatch) -> None:
    """Deux envois qui se suivent demandent leurs chaînes l'un après l'autre : sinon tous deux pourraient croire Crozon pas encore demandée."""
    inside, overlaps = [], []

    def request(city):
        if inside:
            overlaps.append(city)
        inside.append(city)
        threading.Event().wait(0.05)
        inside.remove(city)
    monkeypatch.setattr(etl_pipeline, "request_city_chains", request)

    workers = [etl_pipeline.start_chain_requests(["Crozon"]), etl_pipeline.start_chain_requests(["Crozon"])]
    for worker in workers:
        worker.join(5)

    assert overlaps == []
