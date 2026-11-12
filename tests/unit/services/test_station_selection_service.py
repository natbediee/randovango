"""Le lien Google Maps d'une station : il doit ouvrir la station elle-même (essai du 8 novembre 2026)."""
import json
from datetime import date, datetime

from services.station_selection_service import (closure_label, is_closed_for_good, is_motorway, station_view, price_badges, prices_summary,
                                                station_maps_url)


def test_a_station_with_a_brand_is_searched_as_a_station_of_that_brand_at_its_address():
    """« Intermarché Rue du Stade » ouvrirait le supermarché ; avec « station-service » devant, Google ouvre la station."""
    url = station_maps_url("Intermarché", "RUE DU STADE, 29217 Plougonvelin", "29217", "PLOUGONVELIN", 48.34, -4.72)
    assert url.endswith("query=station-service+Intermarch%C3%A9+RUE+DU+STADE%2C+29217+Plougonvelin")


def test_without_a_usable_address_the_postcode_and_town_of_the_state_are_used():
    """Plouarzel : le champ adresse de l'État est le nom de la société, poi.address est vide."""
    url = station_maps_url("Système U", None, "29810", "PLOUARZEL", 48.43, -4.71)
    assert url.endswith("query=station-service+Syst%C3%A8me+U+29810+Plouarzel")


def test_a_station_without_brand_is_given_by_its_position():
    """Sans marque, la recherche ouvre une liste dont la première station est ailleurs (Locmaria-Plouzané)."""
    url = station_maps_url(None, "rue du Pont de bois, 29280 Locmaria-Plouzané", "29280", "Locmaria-Plouzané",
                           48.37506, -4.64481)
    assert url.endswith("query=48.375060%2C-4.644810")
    assert station_maps_url(" ", None, None, None, None, None) is None


# Les pastilles de prix (maquette du 8 novembre 2026)
TODAY = date(2026, 11, 8)
PRICES = json.dumps([
    {"carburant": "E85", "prix": 0.869, "releve_le": "2026-10-01 12:48:05.000000", "rupture_type": None},
    {"carburant": "GPLc", "prix": None, "releve_le": None, "rupture_type": "definitive"},
    {"carburant": "SP95", "prix": 2.169, "releve_le": "2026-11-03 08:02:07.000000", "rupture_type": "temporaire"},
    {"carburant": "E10", "prix": 2.078, "releve_le": "2026-10-30 12:06:12.000000", "rupture_type": None},
    {"carburant": "Gazole", "prix": 2.178, "releve_le": "2026-11-03 15:19:50.000000", "rupture_type": None},
])


def test_one_badge_per_fuel_sold_diesel_first():
    badges = price_badges(PRICES, TODAY)
    assert [b["label"] for b in badges] == ["Gazole", "SP95-E10", "SP95", "E85"]
    assert badges[0] == {"carburant": "Gazole", "label": "Gazole", "prix": 2.178, "rupture": False,
                         "releve_le": "2026-11-03", "date_label": "3 nov.", "ancien": False}


def test_a_shortage_for_good_has_no_badge_a_temporary_one_has_no_price():
    badges = {b["carburant"]: b for b in price_badges(PRICES, TODAY)}
    assert "GPLc" not in badges
    assert (badges["SP95"]["rupture"], badges["SP95"]["prix"]) == (True, None)


def test_a_price_declared_more_than_seven_days_ago_is_old():
    badges = {b["carburant"]: b for b in price_badges(PRICES, TODAY)}
    assert badges["E85"]["ancien"] and badges["E85"]["date_label"] == "1 oct."
    assert badges["E10"]["ancien"]          # 30 octobre : 9 jours avant le 8 novembre
    assert not badges["Gazole"]["ancien"]   # 3 novembre : 5 jours
    assert price_badges(None, TODAY) == []


def test_the_summary_gives_the_declared_dates_and_the_reading_day():
    badges = price_badges(PRICES, TODAY)
    assert prices_summary(badges, datetime(2026, 11, 8, 18, 29)) == "Prix déclarés du 1 oct. au 3 nov., lus le 8 nov."
    assert prices_summary([], None) is None


def test_closures():
    assert is_closed_for_good("D") and not is_closed_for_good("T")
    assert closure_label("T", datetime(2026, 11, 1), datetime(2026, 11, 12), TODAY) == "Fermée jusqu'au 12 nov."
    assert closure_label("T", datetime(2026, 11, 1), None, TODAY) == "Fermée en ce moment"
    assert closure_label("T", datetime(2026, 11, 20), None, TODAY) is None
    assert closure_label(None, None, None, TODAY) is None


# --- La fiche de supervision d'une station (station_view, carte #180) ---

GUILVINEC = {"poi_id": 48710, "pdv_id": "29730006", "name": "Carrefour", "marque": "Carrefour", "adresse_etat": "1 rue du moulin",
             "code_postal": "29730", "ville_etat": "Guilvinec", "route": "R", "automate_24_24": None,
             "osm_element": "node/6179234430", "lien_osm": "ref_osm", "lu_le": datetime(2026, 11, 11, 21, 21),
             "address": "1 rue du moulin, 29730 Guilvinec", "latitude": 47.805, "longitude": -4.28059,
             "prix": json.dumps([{"carburant": "Gazole", "prix": 2.426, "releve_le": "2026-09-25 07:00:00.000000",
                                  "rupture_type": None},
                                 {"carburant": "SP98", "prix": None, "releve_le": None, "rupture_type": "temporaire"}]),
             "dernieres_nouvelles": datetime(2026, 9, 25, 7, 0)}


def test_the_review_sheet_of_a_station_says_what_the_state_says():
    """Le Carrefour de Guilvinec en supervision : ses prix en ocre, sa dernière déclaration, sa station OSM et le lien Google."""
    view = station_view(GUILVINEC, date(2026, 11, 12))
    assert view["derniere_declaration"] == "25/09/2026" and view["jours_sans_nouvelles"] == 48
    assert view["adresse_etat"] == "1 rue du moulin 29730 Guilvinec"
    assert view["osm_url"] == "https://www.openstreetmap.org/node/6179234430"
    assert [(badge["label"], badge["ancien"], badge["rupture"]) for badge in view["prix"]] == [
        ("Gazole", True, False), ("SP98", False, True)]
    assert "station-service+Carrefour" in view["maps_url"]
    assert view["autoroute"] is False


def test_a_station_never_heard_of_has_no_last_declaration():
    """Une station sans aucun prix ni rupture : pas de date de dernière déclaration, et la fiche le dit."""
    view = station_view({**GUILVINEC, "prix": None, "dernieres_nouvelles": "1000-01-01 00:00:00"}, date(2026, 11, 12))
    assert (view["derniere_declaration"], view["jours_sans_nouvelles"], view["prix"]) == (None, None, [])


def test_a_motorway_station_is_marked():
    """Une station du réseau autoroutier (pop = A dans le fichier de l'État) porte l'étiquette Autoroute."""
    assert station_view({**GUILVINEC, "route": "A"}, date(2026, 11, 12))["autoroute"] is True
    assert is_motorway("A") and not is_motorway("R") and not is_motorway(None)
