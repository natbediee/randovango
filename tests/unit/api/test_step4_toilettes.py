"""
Les toilettes et douches de l'étape 4 (issue #193) : l'étiquette access d'OSM dit à qui elles sont ouvertes.
Réservées aux clients, privées ou fermées : pas montrées ; sans étiquette ou permissive : « non vérifié ».
"""
from test_step4_restaurants import _get_poi, _row


def _facility(poi_id, category, access, payant=None):
    return {**_row(poi_id, f"Toilettes publiques {poi_id}", category, None, None),
            "acces_osm": access, "payant": payant}


def _names(pois):
    return [poi["name"] for poi in pois]


def test_toilets_for_customers_private_or_closed_are_not_shown(monkeypatch):
    """Les toilettes du camping municipal (customers), privées ou fermées ne sont plus montrées « Toilettes publiques »."""
    rows = [_facility(1, "toilets", "customers"), _facility(2, "toilets", "private"),
            _facility(3, "toilets", "no"), _facility(4, "toilets", "yes")]
    result, _ = _get_poi(monkeypatch, rows)
    assert _names(result["toilettes"]) == ["Toilettes publiques 4"]


def test_a_shower_for_customers_is_not_shown(monkeypatch):
    """Une douche réservée aux clients disparaît aussi de l'onglet Hygiène."""
    rows = [_facility(1, "shower", "customers"), _facility(2, "shower", "yes")]
    result, _ = _get_poi(monkeypatch, rows)
    assert _names(result["hygiene"]) == ["Toilettes publiques 2"]


def test_only_access_yes_is_shown_verified(monkeypatch):
    """Sans étiquette ou permissive, la toilette reste montrée mais « non vérifié » ; access=yes garde « Vérifié »."""
    rows = [_facility(1, "toilets", None), _facility(2, "toilets", "permissive"), _facility(3, "toilets", "yes")]
    result, _ = _get_poi(monkeypatch, rows)
    badges = {poi["name"]: poi["badge"]["text"] for poi in result["toilettes"]}
    assert badges == {"Toilettes publiques 1": "Non vérifié", "Toilettes publiques 2": "Non vérifié",
                      "Toilettes publiques 3": "Vérifié"}


def test_a_paying_toilet_is_marked(monkeypatch):
    """Une toilette fee=yes est marquée payante ; gratuite ou inconnue, elle ne l'est pas."""
    rows = [_facility(1, "toilets", "yes", payant=1), _facility(2, "toilets", "yes", payant=0),
            _facility(3, "toilets", "yes")]
    result, _ = _get_poi(monkeypatch, rows)
    assert {poi["name"]: poi["payant"] for poi in result["toilettes"]} == {
        "Toilettes publiques 1": True, "Toilettes publiques 2": False, "Toilettes publiques 3": False}


def test_other_services_ignore_the_access_tag(monkeypatch):
    """Un point d'eau garde son badge de la base : la règle ne touche que les toilettes et douches."""
    rows = [{**_row(1, "Point d'eau potable", "drinking_water", None, None), "acces_osm": None}]
    result, _ = _get_poi(monkeypatch, rows)
    assert result["eau"][0]["badge"]["text"] == "Vérifié"
