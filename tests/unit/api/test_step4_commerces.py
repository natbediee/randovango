from datetime import date

from api.routers import step4
from test_step4_restaurants import _get_poi, _row


def _shop(poi_id, name, category, genre, address, categorie=None, jours=None, latitude=48.34):
    return {**_row(poi_id, name, category, None, address, latitude), "commerce_genre": genre, "commerce_pourquoi": None,
            "commerce_categorie": categorie, "commerce_registre_depuis": None, "jours": jours}


def test_the_query_reads_the_commerce_sheets(monkeypatch):
    _, cursor = _get_poi(monkeypatch, [])
    assert "LEFT JOIN commerces c" in cursor.sql and "c.poi_id IS NOT NULL" in cursor.sql


def test_a_shop_shows_its_category_its_market_day_and_a_maps_link(monkeypatch):
    rows = [{**_shop(1, "Marché de Plougonvelin", "marketplace", "marché", "Place, 29217 Plougonvelin", "marche", "jeudi matin"),
             "commerce_pourquoi": "Le marché du bourg.", "commerce_registre_depuis": date.today()}]
    result, _ = _get_poi(monkeypatch, rows)
    shop = result["commerce"][0]
    assert shop["service_type_label"] == "Marché" and shop["jours"] == "jeudi matin" and shop["description"] == "Le marché du bourg."
    assert "query=March" in shop["maps_url"] and shop["nouveau"] is True


def test_once_treated_only_the_checked_shops_remain_and_supermarkets_stay(monkeypatch):
    rows = [_shop(1, "Le Gall", "bakery", "boulangerie", "1 rue, 29217 Plougonvelin", "boulangerie"),
            _shop(2, "Boulangerie d'OSM", "bakery", None, "2 rue, 29217 Plougonvelin"),
            _shop(3, "Super U", "supermarket", None, "3 rue, 29217 Plougonvelin"),
            _shop(4, "Épicerie voisine", "convenience", None, "1 rue, 29280 Locmaria-Plouzané")]
    result, _ = _get_poi(monkeypatch, rows)
    assert [poi["name"] for poi in result["commerce"]] == ["Le Gall", "Épicerie voisine"]
    assert [poi["name"] for poi in result["supermarche"]] == ["Super U"]
    assert "query=" in result["commerce"][1]["maps_url"]


def test_a_commune_not_treated_keeps_its_osm_shops(monkeypatch):
    rows = [_shop(1, "Boulangerie", "bakery", None, "1 rue, 29217 Plougonvelin"), _shop(2, "Ferme", "farm", None, "2 rue, 29217 Plougonvelin")]
    result, _ = _get_poi(monkeypatch, rows)
    assert {poi["name"] for poi in result["commerce"]} == {"Boulangerie", "Ferme"}


def test_a_shop_sheet_does_not_hide_the_osm_restaurants(monkeypatch):
    rows = [_shop(1, "Le Gall", "bakery", "boulangerie", "1 rue, 29217 Plougonvelin", "boulangerie"),
            _row(2, "Restaurant d'OSM", "restaurant", None, "2 rue, 29217 Plougonvelin")]
    result, _ = _get_poi(monkeypatch, rows)
    assert [poi["name"] for poi in result["restauration"]] == ["Restaurant d'OSM"]


def test_the_commune_shops_show_up_to_fifteen_nearest_the_spot(monkeypatch):
    shops = [_shop(number, f"Commerce {number}", "bakery", "boulangerie", "1 rue, 29217 Plougonvelin", "boulangerie",
                   latitude=48.34 + 0.001 * number) for number in reversed(range(20))]
    result, _ = _get_poi(monkeypatch, shops, spot=(48.34, -4.70))
    assert [poi["name"] for poi in result["commerce"]] == [f"Commerce {number}" for number in range(step4.SHOPS_SHOWN)]


def test_an_osm_shop_without_a_sheet_is_not_shown_verified(monkeypatch):
    rows = [{**_shop(1, "Boulangerie d'OSM", "bakery", None, "1 rue, 29280 Locmaria-Plouzané"), "verifie": 1},
            {**_shop(2, "Le Gall", "bakery", "boulangerie", "2 rue, 29217 Plougonvelin", "boulangerie"), "verifie": 1},
            {**_row(3, "Toilettes", "toilets", None, "3 rue"), "verifie": 1}]
    result, _ = _get_poi(monkeypatch, rows)
    badges = {poi["name"]: poi["badge"]["text"] for category in ("commerce", "toilettes") for poi in result[category]}
    assert badges == {"Boulangerie d'OSM": "Non vérifié", "Le Gall": "Vérifié", "Toilettes": "Vérifié"}


def _get_poi_on(monkeypatch, rows, day):
    cursor_rows = rows
    from test_step4_restaurants import _Cursor
    cursor = _Cursor(cursor_rows)
    connection = type("Connection", (), {"cursor": lambda self, dictionary=False: cursor})()
    monkeypatch.setattr(step4.MySQLUtils, "connect", staticmethod(lambda: connection))
    monkeypatch.setattr(step4.MySQLUtils, "disconnect", staticmethod(lambda connection: None))
    return step4.get_poi(city_id=2, distance_km=5, spot_lat=None, spot_lon=None, day_date=day)


def test_a_place_out_of_season_on_the_trip_day_is_not_shown(monkeypatch):
    fish = {**_shop(1, "Bateau de pêche Kervouroc", "farm", "poissonnier", "1 rue, 29217 Plougonvelin", "producteur"),
            "statut_saison": "confirmee", "mois_ouverture": "[3, 4, 5, 6, 7, 8, 9]"}
    assert _get_poi_on(monkeypatch, [fish], date(2026, 11, 7))["commerce"] == []
    shown = _get_poi_on(monkeypatch, [fish], date(2026, 10, 22))["commerce"]
    assert shown[0]["saison_label"] == "Ouvert d'avril à octobre"


def test_a_probable_season_is_shown_with_a_warning(monkeypatch):
    beach = {**_row(1, "La Balise", "restaurant", "x", "1 bd, 29217 Plougonvelin"), "statut_saison": "probable"}
    shown = _get_poi_on(monkeypatch, [beach], date(2026, 11, 7))["restauration"]
    assert shown[0]["saison_label"] == "Saisonnier, vérifie l'ouverture"


def test_without_a_trip_date_today_is_used(monkeypatch):
    fish = {**_shop(1, "Kervouroc", "farm", "poissonnier", "1 rue, 29217 Plougonvelin", "producteur"),
            "statut_saison": "confirmee", "mois_ouverture": f"[{(date.today().month) % 12}]"}
    assert _get_poi_on(monkeypatch, [fish], None)["commerce"] == []


def test_cafes_and_laundries_have_their_own_tab(monkeypatch):
    rows = [_shop(1, "Le Café du Port", "cafe", "café", "1 quai, 29217 Plougonvelin", "cafe"),
            _row(2, "Laverie du Trez-Hir", "laundry", None, "2 bd, 29217 Plougonvelin")]
    result, _ = _get_poi(monkeypatch, rows)
    assert [poi["name"] for poi in result["cafe"]] == ["Le Café du Port"] and result["cafe"][0]["service_type_label"] == "Café, bar"
    assert [poi["name"] for poi in result["laverie"]] == ["Laverie du Trez-Hir"]
    assert result["restauration"] == [] and result["commerce"] == []


def test_shop_sheets_without_cafes_do_not_hide_the_osm_cafes(monkeypatch):
    """Une commune passée par la version 1 des commerces, qui ne cherchait pas les cafés, garde ses cafés d'OSM."""
    rows = [_shop(1, "Le Gall", "bakery", "boulangerie", "1 rue, 29217 Plougonvelin", "boulangerie"),
            _shop(2, "Bar d'OSM", "cafe", None, "2 rue, 29217 Plougonvelin")]
    result, _ = _get_poi(monkeypatch, rows)
    assert [poi["name"] for poi in result["cafe"]] == ["Bar d'OSM"]
    rows.append(_shop(3, "Le Café du Port", "cafe", "café", "3 quai, 29217 Plougonvelin", "cafe"))
    result, _ = _get_poi(monkeypatch, rows)
    assert [poi["name"] for poi in result["cafe"]] == ["Le Café du Port"]


def test_every_service_card_has_a_maps_link(monkeypatch):
    rows = [{**_row(1, "Laverie", "laundry", None, None), "latitude": 48.3424, "longitude": -4.72313},
            _row(2, "Toilettes publiques", "toilets", None, "Place, 29217 Plougonvelin"),
            _row(3, "Musée", "museum", None, "1 rue, 29217 Plougonvelin"),
            {**_row(4, "Station Total", "fuel", None, "Route, 29217 Plougonvelin"), "source_name": "prix-carburants"}]
    result, _ = _get_poi(monkeypatch, rows)
    assert result["laverie"][0]["maps_url"].endswith("query=48.342400%2C-4.723130")
    assert result["toilettes"][0]["maps_url"].endswith("%2C-4.700000")
    assert "query=Mus%C3%A9e+1+rue" in result["culture"][0]["maps_url"]
    assert result["gasoil"][0]["maps_url"].endswith("%2C-4.700000")    # sans marque : la position


def test_a_place_without_a_position_is_left_out(monkeypatch):
    rows = [{**_shop(1, "Biscuiterie", "farm", "biscuiterie", "Lieu-dit Le Lannou, 29217 Plougonvelin", "producteur"),
             "latitude": None, "longitude": None},
            _shop(2, "Le Gall", "bakery", "boulangerie", "1 rue, 29217 Plougonvelin", "boulangerie")]
    result, _ = _get_poi(monkeypatch, rows)
    assert [poi["name"] for poi in result["commerce"]] == ["Le Gall"]


def test_a_google_maps_link_typed_by_an_admin_wins(monkeypatch):
    rows = [{**_row(1, "Laverie", "laundry", None, None), "maps_saisi": "https://maps.app.goo.gl/AbCdEf123"}]
    result, _ = _get_poi(monkeypatch, rows)
    assert result["laverie"][0]["maps_url"] == "https://maps.app.goo.gl/AbCdEf123"
