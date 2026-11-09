from datetime import date

from api.routers import step4


def _row(poi_id, name, category, genre, address, latitude=48.34):
    return {"id": poi_id, "name": name, "description": None, "latitude": latitude, "longitude": -4.70, "verifie": 1, "image_url": None,
            "url": None, "address": address, "service_category": category, "service_name": category, "genre": genre, "pourquoi": None,
            "budget": None, "jours_fermeture": None, "distinction": None, "categorie": None, "registre_depuis": None,
            "statut_saison": None, "mois_ouverture": None}


class _Cursor:
    def __init__(self, rows):
        self.rows, self.params = rows, None

    def execute(self, sql, params=None):
        if "FROM poi" in sql:
            self.sql, self.params = sql, params

    def fetchone(self):
        return {"name": "Plougonvelin", "latitude": 48.3378, "longitude": -4.70183}

    def fetchall(self):
        return self.rows

    def close(self):
        pass


def _get_poi(monkeypatch, rows, spot=(None, None)):
    cursor = _Cursor(rows)
    connection = type("Connection", (), {"cursor": lambda self, dictionary=False: cursor})()
    monkeypatch.setattr(step4.MySQLUtils, "connect", staticmethod(lambda: connection))
    monkeypatch.setattr(step4.MySQLUtils, "disconnect", staticmethod(lambda connection: None))
    return step4.get_poi(city_id=2, distance_km=5, spot_lat=spot[0], spot_lon=spot[1]), cursor


def test_a_sheet_of_the_commune_beyond_the_zone_is_asked_for(monkeypatch):
    _, cursor = _get_poi(monkeypatch, [])
    assert cursor.params[-1] == "%Plougonvelin" and "p.address LIKE" in cursor.sql


def test_the_commune_sheets_are_not_pushed_out_by_nearer_places(monkeypatch):
    far_sheets = [_row(number, f"Fiche {number}", "restaurant", "x", "7 place, 29217 Plougonvelin", latitude=48.38) for number in range(10)]
    cafe = _row(100, "Café tout proche", "cafe", None, "1 rue, 29217 Plougonvelin")
    result, _ = _get_poi(monkeypatch, [cafe, *far_sheets])
    names = [poi["name"] for poi in result["restauration"]]
    assert len(names) == 10 and "Café tout proche" not in names


def test_the_commune_tables_go_from_the_nearest_to_the_farthest(monkeypatch):
    rows = [{**_row(1, "Crêperie proche", "restaurant", "x", "1 rue, 29217 Plougonvelin"), "categorie": "regionale"},
            {**_row(2, "Autre crêperie", "restaurant", "x", "2 rue, 29217 Plougonvelin"), "categorie": "regionale"},
            {**_row(3, "Pizza", "restaurant", "x", "3 rue, 29217 Plougonvelin", latitude=48.35), "categorie": "pizzeria"},
            {**_row(4, "Étoilé", "restaurant", "x", "4 rue, 29217 Plougonvelin", latitude=48.38), "categorie": "gastronomique", "distinction": "Étoile Michelin"},
            _row(5, "Bistrot d'OSM", "fast_food", None, "5 rue, 29217 Plougonvelin")]
    result, _ = _get_poi(monkeypatch, rows)
    assert [poi["name"] for poi in result["restauration"]] == ["Crêperie proche", "Autre crêperie", "Pizza", "Étoilé", "Bistrot d'OSM"]


def test_a_table_shows_its_category_and_an_old_one_stays_a_restaurant(monkeypatch):
    rows = [{**_row(1, "Riboul", "restaurant", "x", "1 rue, 29217 Plougonvelin"), "categorie": "regionale"},
            _row(2, "Ancienne", "restaurant", "x", "2 rue, 29217 Plougonvelin")]
    result, _ = _get_poi(monkeypatch, rows)
    assert {poi["name"]: poi["service_type_label"] for poi in result["restauration"]} == {"Riboul": "Cuisine régionale", "Ancienne": "restaurant"}


def test_a_table_shows_the_agent_sentence_when_osm_has_no_description(monkeypatch):
    rows = [{**_row(1, "Riboul", "restaurant", "x", "1 rue, 29217 Plougonvelin"), "pourquoi": "Crêperie du bourg."},
            {**_row(2, "Décrite", "restaurant", "x", "2 rue, 29217 Plougonvelin"), "description": "Texte OSM", "pourquoi": "Phrase"}]
    result, _ = _get_poi(monkeypatch, rows)
    assert {poi["name"]: poi["description"] for poi in result["restauration"]} == {"Riboul": "Crêperie du bourg.", "Décrite": "Texte OSM"}


def test_a_place_says_its_distance_from_the_spot(monkeypatch):
    rows = [_row(1, "À côté", "restaurant", "x", "1 rue, 29217 Plougonvelin"),
            _row(2, "Loin", "restaurant", "x", "2 rue, 29217 Plougonvelin", latitude=48.38)]
    result, _ = _get_poi(monkeypatch, rows, spot=(48.34, -4.70))
    labels = {poi["name"]: (poi["near_spot"], poi["reference_distance_label"]) for poi in result["restauration"]}
    assert labels["À côté"] == (True, "Proche de ton spot")
    assert labels["Loin"][0] is False and labels["Loin"][1].endswith("km de ton spot")


def test_without_a_spot_the_distance_is_from_the_centre(monkeypatch):
    result, _ = _get_poi(monkeypatch, [_row(1, "Table", "restaurant", "x", "1 rue, 29217 Plougonvelin")])
    poi = result["restauration"][0]
    assert poi["reference_distance_label"].endswith("du centre") and poi["near_spot"] is False


def test_every_table_of_the_commune_is_shown_beyond_ten(monkeypatch):
    tables = [{**_row(number, f"Table {number}", "restaurant", "x", "1 rue, 29217 Plougonvelin"), "categorie": "regionale"} for number in range(13)]
    result, _ = _get_poi(monkeypatch, [*tables, _row(100, "Café", "cafe", None, "2 rue, 29217 Plougonvelin")])
    assert len(result["restauration"]) == 13


def test_other_categories_keep_their_limit(monkeypatch):
    result, _ = _get_poi(monkeypatch, [_row(number, f"Toilettes {number}", "toilets", None, "1 rue") for number in range(12)])
    assert len(result["toilettes"]) == 10


def test_every_restaurant_and_every_café_has_a_maps_link(monkeypatch):
    rows = [_row(1, "Nom d'OSM", "restaurant", None, "1 rue, 29280 Locmaria-Plouzané"), _row(2, "Café", "cafe", None, "2 rue, 29217 Plougonvelin")]
    result, _ = _get_poi(monkeypatch, rows)
    # Les cafés ont leur onglet depuis le 7 novembre 2026 : la restauration ne garde que les endroits où l'on mange.
    assert "query=Nom+d%27OSM+1+rue" in result["restauration"][0]["maps_url"]
    # Toutes les cartes de services ont le bouton Google Maps (7 novembre 2026), sauf le carburant.
    assert [poi["name"] for poi in result["cafe"]] == ["Café"] and "query=Caf%C3%A9+2+rue" in result["cafe"][0]["maps_url"]


def test_new_comes_from_the_register_date(monkeypatch):
    recent = {**_row(1, "Récent", "restaurant", "x", "1 rue, 29217 Plougonvelin"), "registre_depuis": date.today()}
    old = {**_row(2, "Ancien", "restaurant", "x", "2 rue, 29217 Plougonvelin"), "registre_depuis": date(2000, 6, 26)}
    result, _ = _get_poi(monkeypatch, [recent, old])
    assert {poi["name"]: poi["nouveau"] for poi in result["restauration"]} == {"Récent": True, "Ancien": False}


def test_a_commune_not_treated_keeps_its_own_restaurants(monkeypatch):
    rows = [_row(1, "La Cabane", "restaurant", "x", "1 bd, 29217 Plougonvelin"), _row(2, "La Cormorandière", "restaurant", None, "Place, 29280 Locmaria-Plouzané")]
    result, _ = _get_poi(monkeypatch, rows)
    assert {poi["name"] for poi in result["restauration"]} == {"La Cabane", "La Cormorandière"}


def test_a_big_city_shows_its_fifteen_tables_nearest_the_spot(monkeypatch):
    tables = [_row(number, f"Table {number}", "restaurant", "x", "1 rue, 29217 Plougonvelin", latitude=48.34 + 0.001 * number)
              for number in reversed(range(20))]
    result, _ = _get_poi(monkeypatch, tables, spot=(48.34, -4.70))
    assert [poi["name"] for poi in result["restauration"]] == [f"Table {number}" for number in range(15)]


class _HamletCursor(_Cursor):
    """Trézien, lieu-dit de Plouarzel : les adresses de ses lieux finissent par « 29810 Plouarzel »."""
    queries = 0

    def execute(self, sql, params=None):
        if "FROM poi" in sql:
            self.queries += 1
        super().execute(sql, params)

    def fetchone(self):
        return {"name": "Trézien", "commune": "Plouarzel", "latitude": 48.424, "longitude": -4.76797}


def test_a_hamlet_asks_once_for_the_sheets_of_its_commune(monkeypatch):
    cursor = _HamletCursor([_row(1, "Ty Pesked", "restaurant", "crêperie", "1 rue du Bourg, 29810 Plouarzel")])
    connection = type("Connection", (), {"cursor": lambda self, dictionary=False: cursor})()
    monkeypatch.setattr(step4.MySQLUtils, "connect", staticmethod(lambda: connection))
    monkeypatch.setattr(step4.MySQLUtils, "disconnect", staticmethod(lambda connection: None))
    result = step4.get_poi(city_id=26, distance_km=5, spot_lat=None, spot_lon=None)
    assert cursor.queries == 1 and cursor.params[-1] == "%Plouarzel"
    assert [poi["name"] for poi in result["restauration"]] == ["Ty Pesked"]


def test_a_table_of_the_commune_is_read_after_its_postcode():
    """Ni un nom de rue (route de Trézien), ni une commune voisine qui contient le nom (Lampaul-Plouarzel)."""
    assert step4.is_own_table({"genre": "pizzeria", "address": "5 route de Trézien, 29810 Plouarzel"}, "Plouarzel")
    assert step4.is_own_table({"genre": "crêperie", "address": "1 rue, 29810 PLOUARZEL"}, "Plouarzel")
    assert step4.is_own_table({"genre": "bar", "address": "Le Bourg, 29253 Ile de Batz"}, "Île-de-Batz")
    assert not step4.is_own_table({"genre": "bar", "address": "158 rue de Porscave, 29810 Lampaul-Plouarzel"}, "Plouarzel")
    assert not step4.is_own_table({"genre": "pizzeria", "address": "5 route de Trézien, 29810 Plouarzel"}, "Trézien")
    assert not step4.is_own_table({"genre": "bar", "address": "Rue du Port"}, "Plouarzel")
