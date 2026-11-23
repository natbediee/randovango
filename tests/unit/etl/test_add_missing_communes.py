"""Une ligne par commune dans cities, et les services et spots des lieux-dits repris par leur commune (issue #184)."""
from unittest.mock import MagicMock

from etl import add_missing_communes as script
from utils import geo_utils

LILIA = {"id": 1, "name": "Lilia", "commune": "Plouguerneau", "insee": "29195"}
TREMENACH = {"id": 43, "name": "Tremenac'h", "commune": "Plouguerneau", "insee": "29195"}
LOCHRIST = {"id": 19, "name": "Lochrist", "commune": "Le Conquet", "insee": "29040"}
PLOUGUERNEAU = {"name": "Plouguerneau", "insee": "29195", "latitude": 48.6046, "longitude": -4.5104,
                "department": "Finistère", "region": "Bretagne"}


def test_a_commune_known_only_by_its_localities_is_created_once() -> None:
    """Plouguerneau, connue seulement par Lilia et Tremenac'h, est créée une fois ; Le Conquet, qui a sa ligne, ne l'est pas."""
    assert script.missing_communes([LILIA, TREMENACH, LOCHRIST], {"29040": 33}) == ["29195"]


def test_the_details_of_a_commune_put_the_latitude_first(monkeypatch) -> None:
    """Le centre de Plouguerneau, écrit longitude d'abord par geo.api.gouv.fr, est rangé en latitude et longitude."""
    class Answer:
        def raise_for_status(self):
            pass

        def json(self):
            return {"nom": "Plouguerneau", "code": "29195", "centre": {"type": "Point", "coordinates": [-4.5104, 48.6046]},
                    "departement": {"code": "29", "nom": "Finistère"}, "region": {"code": "53", "nom": "Bretagne"}}

    monkeypatch.setattr(geo_utils.requests, "get", lambda *args, **kwargs: Answer())
    assert geo_utils.get_commune_details("29195") == PLOUGUERNEAU


def test_geo_api_down_creates_no_commune(monkeypatch) -> None:
    """Sans réponse de geo.api.gouv.fr, aucune commune n'est créée à moitié."""
    def down(*args, **kwargs):
        raise geo_utils.requests.ConnectionError("injoignable")
    monkeypatch.setattr(geo_utils, "GEO_API_PAUSE_SECONDS", 0)
    monkeypatch.setattr(geo_utils.requests, "get", down)
    assert geo_utils.get_commune_details("29195") is None


def test_the_links_of_a_locality_are_copied_to_its_commune() -> None:
    """Les services de Lilia sont liés aussi à Plouguerneau, sans doublon et sans retirer le lien à Lilia."""
    cursor = MagicMock()
    script.copy_links(cursor, "histo_poi", locality_id=1, commune_id=140)
    query, params = cursor.execute.call_args.args
    assert query.split()[:3] == ["INSERT", "IGNORE", "INTO"] and "DELETE" not in query
    assert params == (140, 1)


def test_the_trial_creates_nothing(monkeypatch) -> None:
    """À l'essai, Plouguerneau est annoncée mais rien n'est écrit, ni la ville ni sa météo."""
    monkeypatch.setattr(script, "load_localities", lambda cursor: [LILIA, TREMENACH])
    monkeypatch.setattr(script, "load_commune_ids", lambda cursor: {})
    monkeypatch.setattr(script, "get_commune_details", lambda insee: PLOUGUERNEAU)
    weather = MagicMock()
    monkeypatch.setattr(script, "run_meteo_etl", weather)
    connection, cursor = MagicMock(), MagicMock()

    assert script.add_communes(connection, cursor, trial=True) == {"29195": None}
    cursor.execute.assert_not_called()
    connection.commit.assert_not_called()
    weather.assert_not_called()


def test_the_real_run_creates_the_commune_with_its_weather(monkeypatch) -> None:
    """Le passage réel crée Plouguerneau sous son nom officiel, puis charge sa météo pour « Où pars-tu »."""
    monkeypatch.setattr(script, "load_localities", lambda cursor: [LILIA])
    monkeypatch.setattr(script, "load_commune_ids", lambda cursor: {})
    monkeypatch.setattr(script, "get_commune_details", lambda insee: PLOUGUERNEAU)
    weather = MagicMock()
    monkeypatch.setattr(script, "run_meteo_etl", weather)
    connection, cursor = MagicMock(), MagicMock(lastrowid=140)

    assert script.add_communes(connection, cursor, trial=False) == {"29195": 140}
    params = cursor.execute.call_args.args[1]
    assert params[0] == "Plouguerneau" and params[-2:] == ("Plouguerneau", "29195")
    weather.assert_called_once_with("Plouguerneau", 48.6046, -4.5104)
