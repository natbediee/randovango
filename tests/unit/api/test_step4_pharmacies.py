"""
L'onglet Urgences de l'étape 4 et les pharmacies (carte #194) : là où FINESS est passé, seules ses pharmacies sont
montrées ; ailleurs, les pharmacies d'OSM restent.
"""
from test_step4_restaurants import _get_poi, _row


def _pharmacy(poi_id, name, source, address):
    return {**_row(poi_id, name, "pharmacy", None, address), "source_name": source}


def test_where_finess_has_passed_an_unproven_osm_pharmacy_is_not_shown(monkeypatch):
    """Brest : la Pharmacie de Kérinou d'OSM, fermée selon FINESS, n'est plus montrée ; la pharmacie de FINESS l'est."""
    rows = [_pharmacy(1, "Pharmacie de Kérinou", "osm", "82 Rue Auguste Kervern, 29200 Brest"),
            _pharmacy(2, "Pharmacie Fresneau", "finess", "14 Rue Gay Lussac, 29200 Brest")]
    result, _ = _get_poi(monkeypatch, rows)
    assert [poi["name"] for poi in result["urgence"]] == ["Pharmacie Fresneau"]


def test_where_finess_has_not_passed_osm_pharmacies_stay(monkeypatch):
    """Une commune où FINESS n'est pas encore passé garde ses pharmacies d'OSM : l'onglet ne se vide jamais."""
    rows = [_pharmacy(1, "Pharmacie Rivoalen", "osm", "Rue Saint-Yves, 29217 Plougonvelin"),
            _pharmacy(2, "Pharmacie Fresneau", "finess", "14 Rue Gay Lussac, 29200 Brest")]
    result, _ = _get_poi(monkeypatch, rows)
    assert sorted(poi["name"] for poi in result["urgence"]) == ["Pharmacie Fresneau", "Pharmacie Rivoalen"]


def test_without_finess_nearby_every_osm_pharmacy_stays(monkeypatch):
    """Avant tout passage de FINESS, rien ne change : toutes les pharmacies d'OSM sont montrées."""
    rows = [_pharmacy(1, "Pharmacie Rivoalen", "osm", "Rue Saint-Yves, 29217 Plougonvelin"),
            _pharmacy(2, "Pharmacie du Port", "osm", None)]
    result, _ = _get_poi(monkeypatch, rows)
    assert len(result["urgence"]) == 2


def test_the_other_emergency_services_are_kept(monkeypatch):
    """Un médecin d'OSM, dans une commune où FINESS est passé, reste montré : la règle ne touche que les pharmacies."""
    rows = [{**_row(1, "Cabinet médical", "doctors", None, "Rue, 29200 Brest"), "source_name": "osm"},
            _pharmacy(2, "Pharmacie Fresneau", "finess", "14 Rue Gay Lussac, 29200 Brest")]
    result, _ = _get_poi(monkeypatch, rows)
    assert sorted(poi["name"] for poi in result["urgence"]) == ["Cabinet médical", "Pharmacie Fresneau"]


def test_a_finess_pharmacy_links_to_google_maps_with_its_full_address(monkeypatch):
    """Le lien Google Maps d'une pharmacie garde la rue : « Pharmacie Kerros 29200 Brest » seul donnait une liste."""
    rows = [_pharmacy(2, "Pharmacie des Halles", "finess", "9 rue Danton, 29200 Brest")]
    result, _ = _get_poi(monkeypatch, rows)
    assert result["urgence"][0]["maps_url"].endswith("query=Pharmacie+des+Halles+9+rue+Danton%2C+29200+Brest")
