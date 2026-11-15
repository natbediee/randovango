"""
« Où pars-tu » ne propose que des communes, plus les lieux-dits (api/routers/step1.load_communes, issue #184).
La règle est écrite en SQL ; elle est rejouée ici en Python sur des villes réelles, sans base.
"""
from unittest.mock import MagicMock

from api.routers import step1


def _shown(city: dict) -> bool:
    """La règle COMMUNES_ONLY, comme MySQL l'applique : sans tenir compte de la casse (la collation de la table)."""
    return city["commune"] is None or city["name"].lower() == city["commune"].lower()


def test_the_list_query_keeps_only_the_communes() -> None:
    """La requête de « Où pars-tu » filtre les villes par la règle des communes, et garde l'ordre alphabétique."""
    cursor = MagicMock()
    step1.load_communes(cursor)
    query = cursor.execute.call_args.args[0]
    assert f"WHERE {step1.COMMUNES_ONLY}" in query and "ORDER BY name" in query


def test_a_locality_is_no_longer_offered_but_its_commune_is() -> None:
    """Lochrist, lieu-dit du Conquet, n'est plus proposée ; Le Conquet l'est."""
    assert not _shown({"name": "Lochrist", "commune": "Le Conquet"})
    assert _shown({"name": "Le Conquet", "commune": "Le Conquet"})


def test_plouguerneau_replaces_lilia_and_tremenach() -> None:
    """Plouguerneau est proposée, et plus ses lieux-dits Lilia et Tremenac'h."""
    shown = [city["name"] for city in ({"name": "Lilia", "commune": "Plouguerneau"},
                                       {"name": "Tremenac'h", "commune": "Plouguerneau"},
                                       {"name": "Plouguerneau", "commune": "Plouguerneau"}) if _shown(city)]
    assert shown == ["Plouguerneau"]


def test_a_commune_written_with_another_case_stays_offered() -> None:
    """Plounéour-Brignogan-Plages reste proposée, même si l'État l'écrit « -plages »."""
    assert _shown({"name": "Plounéour-Brignogan-Plages", "commune": "Plounéour-Brignogan-plages"})


def test_a_city_whose_commune_is_unknown_stays_offered() -> None:
    """Une ville dont la commune n'est pas encore connue reste proposée : on ne sait pas si c'est un lieu-dit."""
    assert _shown({"name": "Saint-Philibert", "commune": None})
