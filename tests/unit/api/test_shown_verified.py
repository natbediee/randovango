"""Un doute en attente dans la supervision : le service s'affiche « non vérifié », à l'étape 4 comme dans sa fiche."""
from services import poi_edit_service as edit
from test_step4_restaurants import _get_poi, _row
from utils.display_utils import shown_verified, verified_badge


def test_a_pending_doubt_hides_the_badge():
    """Le badge montré est celui de la base, sauf si un signal attend une relecture."""
    assert shown_verified(1, 0) and verified_badge(shown_verified(1, 0))["text"] == "Vérifié"
    assert not shown_verified(1, 1) and verified_badge(shown_verified(1, 1))["text"] == "Non vérifié"
    assert not shown_verified(0, 0)


def test_step4_shows_a_doubted_service_as_not_verified(monkeypatch):
    """À l'étape 4, un restaurant vérifié dont un lien d'OSM attend une relecture s'affiche « non vérifié », et reste affiché."""
    rows = [{**_row(1, "Riboul", "restaurant", "crêperie", "1 rue, 29217 Plougonvelin"), "doute": 1},
            {**_row(2, "La Cabane", "restaurant", "bistrot", "2 rue, 29217 Plougonvelin"), "doute": 0}]
    result, cursor = _get_poi(monkeypatch, rows)
    assert {poi["name"]: poi["verifie"] for poi in result["restauration"]} == {"Riboul": 0, "La Cabane": 1}
    assert "FROM poi_signals doute" in cursor.sql and "doute.statut = 'a_relire'" in cursor.sql


def test_step4_applies_the_rule_to_every_tab(monkeypatch):
    """La règle vaut aussi hors des onglets des agents : un supermarché d'OSM avec un doute en attente n'a plus le badge."""
    rows = [{**_row(1, "Super U", "supermarket", None, "3 rue, 29217 Plougonvelin"), "doute": 1},
            {**_row(2, "Toilettes publiques", "toilets", None, "4 rue, 29217 Plougonvelin"), "doute": 0}]
    result, _ = _get_poi(monkeypatch, rows)
    assert result["supermarche"][0]["verifie"] == 0 and result["toilettes"][0]["verifie"] == 1


def test_the_supervision_sheet_shows_the_same_badge():
    """La fiche de la supervision montre le même badge que l'étape 4 : « non vérifié » tant que le doute n'est pas tranché."""
    poi = {"id": 1, "name": "Super U", "address": "3 rue, 29217 Plougonvelin", "url": None, "maps_url": None, "description": None,
           "statut_saison": None, "mois_ouverture": None, "latitude": 48.34, "longitude": -4.70, "masque": 0, "verifie": 1}
    assert edit.sheet_view({**poi, "doute": 1}, None, "Supermarché")["verifie"] is False
    assert edit.sheet_view({**poi, "doute": 0}, None, "Supermarché")["verifie"] is True
