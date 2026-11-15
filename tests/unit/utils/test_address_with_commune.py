"""
Le lieu-dit d'une adresse devient sa commune (geo_utils.address_with_commune, issue #184, étape 2).
Ni réseau ni base : geo.api.gouv.fr est remplacé par les communes réelles de quelques codes postaux du Finistère.
"""
import pytest

from utils import geo_utils

# La vraie fonction, gardée avant que le conftest ne la remplace pour tous les tests.
REAL_COMMUNES_OF_POSTCODE = geo_utils.communes_of_postcode

# Les communes que l'État donne pour ces codes postaux (geo.api.gouv.fr, 15 novembre 2026).
COMMUNES = {
    "29810": ["Brélès", "Lampaul-Plouarzel", "Plouarzel", "Ploumoguer"],
    "29870": ["Coat-Méal", "Landéda", "Lannilis", "Tréglonou"],
    "29160": ["Crozon", "Lanvéoc"],
    "29880": ["Plouguerneau"],
    "29760": ["Penmarch"],
}


@pytest.fixture(autouse=True)
def fake_geo_api(monkeypatch):
    """geo.api.gouv.fr remplacé : les communes d'un code postal, et la commune qui contient un point."""
    monkeypatch.setattr(geo_utils, "communes_of_postcode", REAL_COMMUNES_OF_POSTCODE)
    monkeypatch.setattr(geo_utils, "POSTCODE_COMMUNES", dict(COMMUNES))
    points = {(48.42, -4.73): ("Plouarzel", "29177"), (48.60, -4.56): ("Landéda", "29101"),
              (48.23, -4.50): ("Crozon", "29042")}
    monkeypatch.setattr(geo_utils, "get_commune_from_coordinates", lambda lat, lon: points.get((lat, lon), (None, None)))


def test_trezien_becomes_plouarzel_and_stays_readable() -> None:
    """Trézien, lieu-dit de Plouarzel, passe sur sa propre ligne, et Plouarzel suit le code postal."""
    assert geo_utils.address_with_commune("Rue de Trézien, 29810 Trézien", 48.42, -4.73) \
        == "Rue de Trézien, Trézien, 29810 Plouarzel"


def test_aber_wrach_becomes_landeda() -> None:
    """L'Aber-Wrac'h, port de Landéda, est rangé à Landéda : la position tranche entre les quatre communes du 29870."""
    assert geo_utils.address_with_commune("Port de l'Aber-Wrac'h, 29870 Aber-Wrac'h", 48.60, -4.56) \
        == "Port de l'Aber-Wrac'h, Aber-Wrac'h, 29870 Landéda"


def test_morgat_becomes_crozon() -> None:
    """Morgat est rangé à Crozon, et pas à Lanvéoc, l'autre commune du 29160."""
    assert geo_utils.address_with_commune("Quai Kador, 29160 Morgat", 48.23, -4.50) == "Quai Kador, Morgat, 29160 Crozon"


def test_a_single_commune_postcode_needs_no_position() -> None:
    """Le 29880 n'a qu'une commune : Tremenac'h est en Plouguerneau, même sans position."""
    assert geo_utils.address_with_commune("553 Korejoù, 29880 Tremenac'h") == "553 Korejoù, Tremenac'h, 29880 Plouguerneau"


def test_a_commune_written_otherwise_takes_its_official_name() -> None:
    """« Penmarc'h » est la commune Penmarch autrement écrite : elle prend son nom officiel, sans ligne de lieu-dit."""
    assert geo_utils.address_with_commune("Rue du Port, 29760 Penmarc'h") == "Rue du Port, 29760 Penmarch"


def test_a_right_address_is_left_alone() -> None:
    """Une adresse qui nomme déjà sa commune, ou déjà réécrite, reste telle quelle : la conversion peut être rejouée."""
    assert geo_utils.address_with_commune("2 rue du Port, 29810 Plouarzel") == "2 rue du Port, 29810 Plouarzel"
    assert geo_utils.address_with_commune("Rue de Trézien, Trézien, 29810 Plouarzel") \
        == "Rue de Trézien, Trézien, 29810 Plouarzel"


def test_an_unknown_commune_leaves_the_address_alone() -> None:
    """Sans position pour départager les communes du code postal, ou sans code postal, on ne devine pas."""
    assert geo_utils.address_with_commune("Quai Kador, 29160 Morgat") == "Quai Kador, 29160 Morgat"
    assert geo_utils.address_with_commune("Bourg de Lampaul") == "Bourg de Lampaul"
    assert geo_utils.address_with_commune(None) is None


def test_the_communes_of_a_postcode_are_asked_once(monkeypatch) -> None:
    """Les communes d'un code postal ne sont demandées qu'une fois à l'API, puis gardées."""
    calls = []

    class Answer:
        def raise_for_status(self):
            pass

        def json(self):
            return [{"nom": "Le Conquet", "code": "29040"}, {"nom": "Plougonvelin", "code": "29190"}]

    monkeypatch.setattr(geo_utils, "POSTCODE_COMMUNES", {})
    monkeypatch.setattr(geo_utils.requests, "get", lambda *args, **kwargs: calls.append(1) or Answer())
    geo_utils.communes_of_postcode("29217")
    assert geo_utils.communes_of_postcode("29217") == ["Le Conquet", "Plougonvelin"]
    assert len(calls) == 1


def test_geo_api_down_is_not_remembered(monkeypatch) -> None:
    """Sans réponse de l'API, rien n'est gardé : le code postal sera redemandé la fois suivante."""
    def down(*args, **kwargs):
        raise geo_utils.requests.ConnectionError("injoignable")
    monkeypatch.setattr(geo_utils, "POSTCODE_COMMUNES", {})
    monkeypatch.setattr(geo_utils.requests, "get", down)
    assert geo_utils.communes_of_postcode("29217") == []
    assert "29217" not in geo_utils.POSTCODE_COMMUNES
