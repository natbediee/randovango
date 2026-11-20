"""L'étape OSM d'une ville : le nombre de lieux chargés, ou None quand OSM ne répond pas."""
from unittest.mock import MagicMock

import pandas as pd
import pytest

from etl import etl_osm
from services import poi_duplicates_service


@pytest.fixture
def steps(monkeypatch):
    fake = MagicMock()
    fake.extract.return_value = {"elements": [{"id": 1}]}
    fake.transform.return_value = pd.DataFrame([{"osm_id": 1}, {"osm_id": 2}])
    monkeypatch.setattr(etl_osm, "extract_osm", fake.extract)
    monkeypatch.setattr(etl_osm, "transform_osm", fake.transform)
    monkeypatch.setattr(etl_osm, "load_osm_poi", fake.load)
    monkeypatch.setattr(poi_duplicates_service, "after_load", fake.duplicates)
    return fake


def test_success_returns_the_number_of_places(steps) -> None:
    """Dinard chargée : l'étape rend le nombre de lieux retenus, puis la règle des doublons repasse sur la ville."""
    assert etl_osm.run_osm_etl("Dinard") == 2
    steps.load.assert_called_once()
    steps.duplicates.assert_called_once_with("Dinard")


def test_failure_returns_none_and_nothing_is_loaded(steps) -> None:
    """OSM muet pour Dinard : l'étape rend None (la chaîne « osm » en fait un échec gardé en base), rien n'est chargé."""
    steps.extract.return_value = None
    assert etl_osm.run_osm_etl("Dinard") is None
    steps.transform.assert_not_called()
    steps.load.assert_not_called()


def test_a_loading_error_goes_up_to_the_chain(steps) -> None:
    """Une erreur de MySQL au chargement remonte : la chaîne « osm » la garde comme raison de l'échec."""
    steps.load.side_effect = RuntimeError("MySQL indisponible")
    with pytest.raises(RuntimeError):
        etl_osm.run_osm_etl("Dinard")
