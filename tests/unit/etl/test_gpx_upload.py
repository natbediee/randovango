"""
L'ajout d'une rando dit ce qui s'est vraiment passé (issue #266) : un GPX sans trace, sans commune au départ ou
déjà en base reçoit un refus avec son motif, et ne reste pas dans le dossier d'attente.

Les petits GPX d'essai sont dans gpx_samples/ ; chaque test les copie dans un dossier temporaire qui joue le dossier
d'attente. Ni base ni réseau : la recherche de la commune et l'enregistrement en base sont remplacés.
"""
import inspect
import shutil
from pathlib import Path
from unittest.mock import MagicMock

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
    monkeypatch.setattr(etl_router, "UPLOAD_DIR", tmp_path / "envoi")
    monkeypatch.setattr(gpx, "gpx_already_in_mysql", lambda fname: False)
    monkeypatch.setattr(gpx, "find_same_path_hike", lambda points: None)
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


# Deux randos en base, telles que les rend find_same_path_hike : le Gouet Nord, identique au tracé envoyé (même
# chemin, même départ), et la pointe Saint-Gildas, recouverte à 86 % avec un départ à 2,6 km.
GOUET_NORD = {"id": 307, "name": "Tour de la retenue du Gouet Nord", "city": "Ploufragan", "share": 1.0,
              "start_gap_m": 0, "identical": True}
SAINT_GILDAS = {"id": 325, "name": "Pointe Saint-Gildas", "city": "Préfailles", "share": 0.86,
                "start_gap_m": 2600, "identical": False}


def test_a_trace_on_the_path_of_a_hike_in_base_is_refused_with_its_name(waiting_dir, commune_found, monkeypatch) -> None:
    """Un tracé renommé qui suit le chemin d'une rando déjà en base est refusé avec le nom de cette rando (cas du Gouet Nord 2, rando 305)."""
    monkeypatch.setattr(gpx, "find_same_path_hike", lambda points: GOUET_NORD)
    path = drop_sample(waiting_dir, "trace.gpx", name="Tour de la retenue du Gouet Nord 2.gpx")

    result = gpx.read_gpx_file(path, path.name)

    assert result["reason"] == ("ce tracé est identique à la rando « Tour de la retenue du Gouet Nord » (Ploufragan),"
                                " qui part du même endroit")
    assert (result["data"], result["same_path"]) == (None, GOUET_NORD)
    assert not path.exists()


def test_a_gpx_with_a_track_is_ready_to_load(waiting_dir, commune_found) -> None:
    """Une vraie trace est prête à charger, rattachée au Conquet ; elle attend le chargement dans le dossier."""
    path = drop_sample(waiting_dir, "trace.gpx")

    result = gpx.read_gpx_file(path, "trace.gpx")

    assert result["reason"] is None
    assert result["data"]["city_name"] == "Le Conquet"
    assert path.exists()


def test_an_uppercase_extension_is_read_too(waiting_dir) -> None:
    """Un « RANDO.GPX », que la route accepte, est pris dans le dossier d'attente au lieu d'y rester oublié ; le sous-dossier du front n'en fait pas partie."""
    drop_sample(waiting_dir, "route_only.gpx", name="RANDO.GPX")
    (waiting_dir / "envoi").mkdir()

    assert gpx.waiting_files() == ["RANDO.GPX"]


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
    """Dans le dossier d'attente, seule la rando chargée lance la météo et les chaînes de sa ville ; la route refusée ne lance rien et quitte le dossier."""
    monkeypatch.setattr(etl_pipeline, "load_gpx_data", lambda data, gpx_path, verifie: data["city_name"])
    completed = []
    monkeypatch.setattr(etl_pipeline, "load_weather", completed.append)
    monkeypatch.setattr(etl_pipeline, "request_chains_of_cities", lambda cities, origin="etl": None)
    drop_sample(waiting_dir, "trace.gpx")
    drop_sample(waiting_dir, "route_only.gpx")

    outcomes = etl_pipeline.process_waiting_folder(user_role="admin")

    assert [(o["filename"], o["city"], o["reason"]) for o in outcomes] == [
        ("route_only.gpx", None, gpx.ROUTE_ONLY),
        ("trace.gpx", "Le Conquet", None),
    ]
    assert completed == ["Le Conquet"]
    assert gpx.waiting_files() == ["trace.gpx"]   # le faux chargement ne retire pas le fichier ; le vrai le retire


@pytest.fixture
def upload_client(waiting_dir, commune_found, monkeypatch):
    """La vraie route upload_gpx, pour un contributeur connecté ; le journal d'audit et la base sont remplacés."""
    monkeypatch.setattr(etl_router, "get_roles_for_user", lambda user_id: ["user"])
    monkeypatch.setattr(etl_router, "insert_auth_log", lambda **kwargs: None)
    monkeypatch.setattr(etl_pipeline, "load_gpx_data", lambda data, gpx_path, verifie: data["city_name"])
    monkeypatch.setattr(etl_pipeline, "load_weather", lambda city: None)
    monkeypatch.setattr(etl_pipeline, "start_chain_requests", lambda cities, origin="etl": None)
    monkeypatch.setattr(etl_pipeline, "start_folder_worker", lambda role: None)
    app = FastAPI()
    app.include_router(etl_router.router, prefix="/api/etl")
    app.dependency_overrides[dependencies.require_contributor] = lambda: {"user_id": 7, "username": "contributrice"}
    return TestClient(app)


def send(client, sample, name=None, load_anyway=False):
    """Envoie un GPX d'essai à la route upload_gpx, comme la page d'ajout, et rend la réponse JSON."""
    content = (SAMPLES / sample).read_bytes()
    form = {"load_anyway": "true"} if load_anyway else {}
    return client.post("/api/etl/upload_gpx", files={"file": (name or sample, content, "application/gpx+xml")},
                       data=form).json()


def test_the_upload_route_answers_a_refusal_with_its_reason(upload_client, waiting_dir) -> None:
    """La page d'ajout reçoit un échec qui dit pourquoi la route seule n'est pas chargée, et le dossier reste vide."""
    answer = send(upload_client, "route_only.gpx")

    assert answer["success"] is False
    assert answer["message"] == f"Fichier route_only.gpx non chargé : {gpx.ROUTE_ONLY}."
    assert list((waiting_dir / "envoi").iterdir()) == []


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


def test_the_upload_answers_for_its_own_file_and_leaves_the_folder_to_the_background(upload_client, waiting_dir, monkeypatch) -> None:
    """Le cas du 27 novembre 2026 : le fichier du front répond sans attendre les 265 fichiers d'un envoi en masse, laissés au fil de fond."""
    started = []
    monkeypatch.setattr(etl_pipeline, "start_folder_worker", started.append)
    drop_sample(waiting_dir, "route_only.gpx", name="envoi-en-masse.gpx")

    answer = send(upload_client, "trace.gpx")

    assert (answer["success"], answer["city"]) == (True, "Le Conquet")
    assert gpx.waiting_files() == ["envoi-en-masse.gpx"]
    assert started == ["user"]


def in_base(monkeypatch, hike) -> None:
    """Cette rando est en base, et tout tracé envoyé suit son chemin."""
    monkeypatch.setattr(gpx, "find_same_path_hike", lambda points: hike)


def as_admin(monkeypatch) -> None:
    """La personne connectée est l'admin."""
    monkeypatch.setattr(etl_router, "get_roles_for_user", lambda user_id: ["admin"])


def test_a_contributor_cannot_load_a_trace_on_the_path_of_a_hike_in_base(upload_client, monkeypatch) -> None:
    """Un contributeur reçoit le refus avec le nom de la rando en base, sans bouton pour charger quand même, même s'il le demande."""
    in_base(monkeypatch, SAINT_GILDAS)

    answer = send(upload_client, "trace.gpx", name="Saint-Gildas.gpx")
    forced = send(upload_client, "trace.gpx", name="Saint-Gildas.gpx", load_anyway=True)

    assert (answer["success"], answer["same_path_hike"], answer["can_load_anyway"]) == (
        False, "Pointe Saint-Gildas", False)
    assert forced["success"] is False


def test_the_admin_can_load_a_trace_on_the_path_of_a_hike_in_base(upload_client, monkeypatch) -> None:
    """L'admin voit le refus avec la rando en base, puis charge quand même le tracé en confirmant : un départ à 2,6 km peut avoir son intérêt (cas de Préfailles)."""
    in_base(monkeypatch, SAINT_GILDAS)
    as_admin(monkeypatch)

    answer = send(upload_client, "trace.gpx", name="Saint-Gildas.gpx")
    confirmed = send(upload_client, "trace.gpx", name="Saint-Gildas.gpx", load_anyway=True)

    assert (answer["success"], answer["can_load_anyway"]) == (False, True)
    assert (confirmed["success"], confirmed["city"]) == (True, "Le Conquet")


def test_an_identical_trace_is_refused_even_for_the_admin(upload_client, monkeypatch) -> None:
    """Un tracé identique à une rando en base (même chemin, même départ) est refusé à l'admin aussi, sans bouton, même s'il confirme (cas du Gouet Nord 2)."""
    in_base(monkeypatch, GOUET_NORD)
    as_admin(monkeypatch)

    answer = send(upload_client, "trace.gpx", name="Gouet Nord 2.gpx")
    forced = send(upload_client, "trace.gpx", name="Gouet Nord 2.gpx", load_anyway=True)

    assert (answer["success"], answer["can_load_anyway"]) == (False, False)
    assert forced["success"] is False
    assert "identique" in forced["message"]


def test_a_waiting_folder_file_on_the_path_of_a_hike_in_base_stays_refused(waiting_dir, commune_found, monkeypatch) -> None:
    """Dans un envoi en masse, personne ne confirme : un tracé qui suit le chemin d'une rando en base est refusé et quitte le dossier."""
    in_base(monkeypatch, SAINT_GILDAS)
    monkeypatch.setattr(etl_pipeline, "load_gpx_data", lambda data, gpx_path, verifie: data["city_name"])
    drop_sample(waiting_dir, "trace.gpx", name="Saint-Gildas.gpx")

    outcomes = etl_pipeline.process_waiting_folder(user_role="admin")

    assert outcomes[0]["same_path"] == SAINT_GILDAS
    assert gpx.waiting_files() == []


@pytest.fixture
def start_in_switzerland(monkeypatch):
    """Le départ de la trace est à Finhaut, en Suisse : aucune commune française, Nominatim dit « Suisse »."""
    monkeypatch.setattr(transform_gpx, "get_commune_at", lambda lat, lon: None)
    monkeypatch.setattr(transform_gpx, "get_city_from_coordinates", lambda *args, **kwargs: "Finhaut")
    monkeypatch.setattr(transform_gpx, "get_admin_info_from_coordinates",
                        lambda lat, lon: ("Bas-Valais", "Valais", "Suisse"))


def test_a_hike_starting_outside_france_is_loaded_with_a_warning(upload_client, start_in_switzerland) -> None:
    """Une rando partie de Suisse est chargée, et la page d'ajout dit ce qui manquera : pharmacies et carburants (cas de Finhaut)."""
    answer = send(upload_client, "trace.gpx", name="Boucle d'Émosson.gpx")

    assert (answer["success"], answer["city"]) == (True, "Finhaut")
    assert answer["warning"] == gpx.OUTSIDE_FRANCE.format(country="Suisse")
    assert "pharmacies" in answer["warning"] and "carburants" in answer["warning"]


def test_a_hike_starting_in_france_has_no_warning(upload_client) -> None:
    """Une rando partie d'une commune française est chargée sans avertissement."""
    answer = send(upload_client, "trace.gpx")

    assert (answer["success"], answer["warning"]) == (True, None)


def test_a_waiting_folder_hike_outside_france_is_loaded_and_logged(waiting_dir, start_in_switzerland, monkeypatch) -> None:
    """Dans un envoi en masse, la rando partie de Suisse est chargée, et l'avertissement est écrit dans les logs, faute de page pour le montrer."""
    monkeypatch.setattr(etl_pipeline, "load_gpx_data", lambda data, gpx_path, verifie: data["city_name"])
    monkeypatch.setattr(etl_pipeline, "load_weather", lambda city: None)
    monkeypatch.setattr(etl_pipeline, "request_chains_of_cities", lambda cities: None)
    warnings = []
    monkeypatch.setattr(etl_pipeline.logger, "warning", warnings.append)
    drop_sample(waiting_dir, "trace.gpx", name="Boucle d'Émosson.gpx")

    outcomes = etl_pipeline.process_waiting_folder(user_role="admin")

    assert (outcomes[0]["city"], outcomes[0]["reason"]) == ("Finhaut", None)
    assert any("Départ hors de France (Suisse)" in line for line in warnings)


@pytest.mark.parametrize("received, kept", [
    ("trace.gpx", "trace.gpx"),
    ("Mont Saint-Michel.GPX", "Mont Saint-Michel.GPX"),
    ("../../trace.gpx", "trace.gpx"),
    ("/etc/cron.d/trace.gpx", "trace.gpx"),
    ("..\\..\\trace.gpx", "trace.gpx"),
])
def test_the_received_name_keeps_no_path(received, kept) -> None:
    """Le nom reçu du navigateur ne garde que le nom du fichier, jamais les dossiers qui le précèdent (issue #213)."""
    assert etl_router.safe_gpx_name(received) == kept


@pytest.mark.parametrize("received", [None, "", "trace", "trace.exe", "trace.gpx.exe", ".gpx", "..", "../..", "trace\0.gpx"])
def test_a_name_without_gpx_extension_is_refused(received) -> None:
    """Un nom vide, caché ou qui ne finit pas par .gpx est refusé (issue #213)."""
    assert etl_router.safe_gpx_name(received) is None


def test_a_name_climbing_up_folders_stays_in_the_waiting_folder(upload_client, waiting_dir, monkeypatch) -> None:
    """Un fichier nommé « ../../trace.gpx » est écrit dans le sous-dossier d'envoi sous le nom trace.gpx, et nulle part au-dessus (issue #213)."""
    written = []
    monkeypatch.setattr(etl_router, "process_upload", lambda path, **kwargs: written.append(path) or {
        "filename": path.name, "city": "Le Conquet", "reason": None})

    answer = send(upload_client, "trace.gpx", name="../../trace.gpx")

    assert written == [waiting_dir / "envoi" / "trace.gpx"]
    assert answer["message"] == "Nouveau tracé sur Le Conquet (fichier trace.gpx)."
    assert not (waiting_dir.parent / "trace.gpx").exists()


def test_the_upload_route_refuses_a_file_that_is_not_gpx(upload_client, waiting_dir) -> None:
    """Un fichier qui n'est pas un .gpx est refusé avec un message clair, sans rien écrire dans le dossier (issue #213)."""
    answer = send(upload_client, "trace.gpx", name="trace.exe")

    assert (answer["success"], answer["message"]) == (False, etl_router.REFUSED_NAME_MESSAGE)
    assert not (waiting_dir / "envoi").exists()


def test_a_failed_upload_does_not_show_the_internal_error(upload_client, waiting_dir, monkeypatch) -> None:
    """Un chargement qui plante répond un message simple : le texte de l'erreur, qui peut montrer la base, reste dans le journal (issue #213)."""
    def failing_upload(path, **kwargs):
        raise RuntimeError("Access denied for user 'root'@'db_randovango' (using password: YES)")
    monkeypatch.setattr(etl_router, "process_upload", failing_upload)
    monkeypatch.setattr(etl_router, "logger", MagicMock())

    answer = send(upload_client, "trace.gpx")

    assert (answer["success"], answer["message"]) == (False, etl_router.UPLOAD_FAILED_MESSAGE)
    assert "root" not in str(answer)
    etl_router.logger.error.assert_called_once()
    assert list((waiting_dir / "envoi").iterdir()) == []
