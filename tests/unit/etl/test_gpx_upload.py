"""
L'ajout d'une rando dit ce qui s'est vraiment passé (issue #266) : un GPX sans trace, sans commune au départ ou
déjà en base reçoit un refus avec son motif, et ne reste pas dans le dossier d'attente.

Les petits GPX d'essai sont dans gpx_samples/ ; chaque test les copie dans un dossier temporaire qui joue le dossier
d'attente. Ni base ni réseau : la recherche de la commune et l'enregistrement en base sont remplacés.
"""
import inspect
import shutil
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import dependencies
from api.routers import etl as etl_router
from etl import etl_pipeline
from etl.extract import gpx
from etl.transform import transform_gpx

SAMPLES = Path(__file__).parent / "gpx_samples"
CONQUET = {"name": "Le Conquet", "insee": "29040", "department": "Finistère", "region": "Bretagne"}


@pytest.fixture
def waiting_dir(tmp_path, monkeypatch):
    """Un dossier d'attente vide, à la place de /usr/src/data, et aucune rando encore en base."""
    monkeypatch.setattr(gpx, "GPX_DIR", tmp_path)
    monkeypatch.setattr(etl_router, "GPX_DIR", tmp_path)
    monkeypatch.setattr(gpx, "gpx_already_in_mysql", lambda fname: False)
    return tmp_path


@pytest.fixture
def commune_found(monkeypatch):
    """Le départ de la trace est au Conquet, que l'État reconnaît comme commune."""
    monkeypatch.setattr(transform_gpx, "get_commune_at", lambda lat, lon: CONQUET)
    monkeypatch.setattr(transform_gpx, "get_city_from_coordinates", lambda *args, **kwargs: "Le Conquet")


def drop_sample(waiting_dir, sample, name=None) -> Path:
    """Dépose un GPX d'essai dans le dossier d'attente, comme la route upload_gpx, et rend son chemin."""
    path = waiting_dir / (name or sample)
    shutil.copy(SAMPLES / sample, path)
    return path


@pytest.mark.parametrize("sample, reason", [
    ("route_only.gpx", gpx.ROUTE_ONLY),
    ("waypoints_only.gpx", gpx.NO_TRACK),
    ("broken.gpx", gpx.UNREADABLE),
])
def test_a_gpx_without_track_is_refused_and_removed(waiting_dir, commune_found, sample, reason) -> None:
    """Un GPX sans trace (une route seule, des points seuls, un fichier cassé) est refusé avec son motif et retiré."""
    path = drop_sample(waiting_dir, sample)

    result = gpx.read_gpx_file(path, sample)

    assert (result["data"], result["reason"]) == (None, reason)
    assert not path.exists()


def test_a_gpx_without_commune_at_start_is_refused_and_removed(waiting_dir, monkeypatch) -> None:
    """Une trace dont le départ n'est dans aucune commune connue est refusée : lieu de départ introuvable."""
    monkeypatch.setattr(transform_gpx, "get_commune_at", lambda lat, lon: None)
    monkeypatch.setattr(transform_gpx, "get_city_from_coordinates", lambda *args, **kwargs: None)
    path = drop_sample(waiting_dir, "trace.gpx")

    result = gpx.read_gpx_file(path, "trace.gpx")

    assert result["reason"] == gpx.START_NOT_FOUND
    assert not path.exists()


def test_a_gpx_already_in_mysql_is_refused_and_removed(waiting_dir, commune_found, monkeypatch) -> None:
    """Un fichier dont le nom est déjà celui d'une rando en base est refusé : rando déjà en base."""
    monkeypatch.setattr(gpx, "gpx_already_in_mysql", lambda fname: True)
    path = drop_sample(waiting_dir, "trace.gpx")

    assert gpx.read_gpx_file(path, "trace.gpx")["reason"] == gpx.ALREADY_LOADED
    assert not path.exists()


def test_a_gpx_with_a_track_is_ready_to_load(waiting_dir, commune_found) -> None:
    """Une vraie trace est prête à charger, rattachée au Conquet ; elle attend le chargement dans le dossier."""
    path = drop_sample(waiting_dir, "trace.gpx")

    result = gpx.read_gpx_file(path, "trace.gpx")

    assert result["reason"] is None
    assert result["data"]["city_name"] == "Le Conquet"
    assert path.exists()


def test_an_uppercase_extension_is_read_too(waiting_dir, commune_found) -> None:
    """Un « RANDO.GPX », que la route accepte, est lu lui aussi au lieu de rester oublié dans le dossier."""
    drop_sample(waiting_dir, "route_only.gpx", name="RANDO.GPX")

    results = gpx.extract_all_gpx_files()

    assert [(r["filename"], r["reason"]) for r in results] == [("RANDO.GPX", gpx.ROUTE_ONLY)]
    assert not (waiting_dir / "RANDO.GPX").exists()


def test_a_trace_already_in_mongo_is_reported_as_already_loaded(waiting_dir, commune_found, monkeypatch) -> None:
    """Un tracé déjà dans MongoDB (le chargement ne rend pas de ville) est annoncé « déjà en base », pas importé."""
    monkeypatch.setattr(etl_pipeline, "load_gpx_data", lambda data, gpx_path, verifie: None)
    path = drop_sample(waiting_dir, "trace.gpx")

    outcome = etl_pipeline.load_one_gpx(gpx.read_gpx_file(path, "trace.gpx"), verifie=1)

    assert outcome == {"filename": "trace.gpx", "city": None, "reason": gpx.ALREADY_LOADED}


def test_a_database_error_refuses_the_file_and_removes_it(waiting_dir, commune_found, monkeypatch) -> None:
    """Une erreur de base pendant le chargement donne un refus, et le fichier ne reste pas dans le dossier."""
    def failing_load(data, gpx_path, verifie):
        raise RuntimeError("MySQL injoignable")
    monkeypatch.setattr(etl_pipeline, "load_gpx_data", failing_load)
    path = drop_sample(waiting_dir, "trace.gpx")

    outcome = etl_pipeline.load_one_gpx(gpx.read_gpx_file(path, "trace.gpx"), verifie=1)

    assert outcome["reason"] == gpx.LOAD_FAILED
    assert not path.exists()


def test_only_loaded_hikes_complete_their_city(waiting_dir, commune_found, monkeypatch) -> None:
    """Seule la rando chargée lance la météo et les services de sa ville ; la route refusée ne lance rien."""
    monkeypatch.setattr(etl_pipeline, "load_gpx_data", lambda data, gpx_path, verifie: data["city_name"])
    completed = []
    monkeypatch.setattr(etl_pipeline, "complete_cities", completed.extend)
    drop_sample(waiting_dir, "trace.gpx")
    drop_sample(waiting_dir, "route_only.gpx")

    outcomes = sorted(etl_pipeline.main(user_role="admin"), key=lambda o: o["filename"])

    assert [(o["filename"], o["city"], o["reason"]) for o in outcomes] == [
        ("route_only.gpx", None, gpx.ROUTE_ONLY),
        ("trace.gpx", "Le Conquet", None),
    ]
    assert completed == ["Le Conquet"]


@pytest.fixture
def upload_client(waiting_dir, commune_found, monkeypatch):
    """La vraie route upload_gpx, pour un contributeur connecté ; le journal d'audit et la base sont remplacés."""
    monkeypatch.setattr(etl_router, "get_roles_for_user", lambda user_id: ["user"])
    monkeypatch.setattr(etl_router, "insert_auth_log", lambda **kwargs: None)
    monkeypatch.setattr(etl_pipeline, "load_gpx_data", lambda data, gpx_path, verifie: data["city_name"])
    monkeypatch.setattr(etl_pipeline, "complete_cities", lambda cities: None)
    app = FastAPI()
    app.include_router(etl_router.router, prefix="/api/etl")
    app.dependency_overrides[dependencies.get_current_user] = lambda: {"user_id": 7, "username": "contributrice"}
    return TestClient(app)


def send(client, sample, name=None):
    """Envoie un GPX d'essai à la route upload_gpx, comme la page d'ajout, et rend la réponse JSON."""
    content = (SAMPLES / sample).read_bytes()
    return client.post("/api/etl/upload_gpx", files={"file": (name or sample, content, "application/gpx+xml")}).json()


def test_the_upload_route_answers_a_refusal_with_its_reason(upload_client, waiting_dir) -> None:
    """La page d'ajout reçoit un échec qui dit pourquoi la route seule n'est pas chargée, et le dossier reste vide."""
    answer = send(upload_client, "route_only.gpx")

    assert answer["success"] is False
    assert answer["message"] == f"Fichier route_only.gpx non chargé : {gpx.ROUTE_ONLY}."
    assert list(waiting_dir.iterdir()) == []


def test_the_upload_route_answers_success_with_the_city(upload_client) -> None:
    """Une trace chargée est annoncée avec sa ville, comme avant l'issue #266."""
    answer = send(upload_client, "trace.gpx")

    assert (answer["success"], answer["city"]) == (True, "Le Conquet")
    assert answer["message"] == "Nouveau tracé sur Le Conquet (fichier trace.gpx)."


def test_a_refused_file_does_not_come_back_with_the_next_upload(upload_client) -> None:
    """Le cas réel : un fichier refusé ne repasse plus au chargement de l'envoi suivant."""
    send(upload_client, "waypoints_only.gpx")

    answer = send(upload_client, "trace.gpx")

    assert answer["success"] is True
    assert answer["message"] == "Nouveau tracé sur Le Conquet (fichier trace.gpx)."


def test_the_upload_route_does_not_hold_the_server() -> None:
    """La route d'envoi est une route « def » : FastAPI la fait tourner à part, et l'application répond pendant un envoi (5 minutes sans réponse le 25 novembre 2026)."""
    assert not inspect.iscoroutinefunction(etl_router.upload_gpx)
