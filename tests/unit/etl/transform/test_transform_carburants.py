"""Le fichier de l'État et le lien avec OSM, sur les cas du pilote du 7 novembre 2026."""
from datetime import datetime

from etl.transform.transform_carburants import (DEFAULT_NAME, file_signals, keep_near, last_news, link_signals,
                                                link_to_osm, osm_station, parse_state_file, station_rows,
                                                usable_address)

XML = """<?xml version="1.0" encoding="ISO-8859-1" standalone="yes"?>
<pdv_liste>
  <pdv id="29217001" latitude="4834200" longitude="-472300" cp="29217" pop="R">
    <adresse>RUE DU STADE</adresse>
    <ville>PLOUGONVELIN</ville>
    <horaires automate-24-24="1">
      <jour id="1" nom="Lundi" ferme=""/>
      <jour id="7" nom="Dimanche" ferme="1"/>
    </horaires>
    <services><service>Boutique alimentaire</service><service>Station de gonflage</service></services>
    <prix nom="Gazole" id="1" maj="2026-11-03 15:19:50" valeur="2.178"/>
    <prix nom="E85" id="3" maj="2026-10-01 12:48:05" valeur="0.869"/>
    <rupture nom="GPLc" id="4" debut="2017-09-27 11:38:49" fin="" type="definitive"/>
  </pdv>
  <pdv id="29810002" latitude="4843200" longitude="-472100" cp="29810" pop="R">
    <adresse>SAS SNDL MENEZ CRENN</adresse>
    <ville>Plouarzel</ville>
    <prix nom="E10" id="5" maj="2026-11-07 08:00:00" valeur="1.999"/>
    <rupture nom="SP98" id="6" debut="2026-11-03 15:49:44" fin="" type="temporaire"/>
  </pdv>
</pdv_liste>""".encode("iso-8859-1")


def _osm(element_id, lat, lon, ref=None, name=None, brand=None, postcode=None):
    tags = {"amenity": "fuel", **({"ref:FR:prix-carburants": ref} if ref else {}),
            **({"name": name} if name else {}), **({"brand": brand} if brand else {}),
            **({"addr:postcode": postcode} if postcode else {})}
    return osm_station({"type": "node", "id": element_id, "lat": lat, "lon": lon, "tags": tags})


def test_the_state_file_is_read_with_its_dates_and_shortages():
    plougonvelin, plouarzel = parse_state_file(XML)
    assert (plougonvelin["latitude"], plougonvelin["longitude"]) == (48.342, -4.723)
    assert plougonvelin["carburants"]["Gazole"] == {"prix": 2.178, "releve_le": datetime(2026, 11, 3, 15, 19, 50),
                                                     "rupture_type": None, "rupture_debut": None, "rupture_fin": None}
    assert plougonvelin["carburants"]["E85"]["releve_le"] == datetime(2026, 10, 1, 12, 48, 5)
    assert plougonvelin["carburants"]["GPLc"]["prix"] is None
    assert plougonvelin["carburants"]["GPLc"]["rupture_type"] == "definitive"
    assert plouarzel["carburants"]["SP98"]["rupture_debut"] == datetime(2026, 11, 3, 15, 49, 44)


def test_a_day_without_slots_is_open_and_a_closed_day_says_so():
    plougonvelin, plouarzel = parse_state_file(XML)
    assert plougonvelin["automate_24_24"] == 1
    assert plougonvelin["horaires"] == {"Lundi": [], "Dimanche": "ferme"}
    assert plougonvelin["services"] == ["Boutique alimentaire", "Station de gonflage"]
    assert plouarzel["horaires"] is None


def test_only_stations_in_the_square_around_the_city_are_kept():
    stations = parse_state_file(XML)
    assert [s["pdv_id"] for s in keep_near(stations, 48.3426, -4.7213, 5)] == ["29217001"]


def test_the_state_identifier_wins_even_when_the_state_position_is_rounded():
    """Station U de Plouarzel : 389 m entre la position arrondie de l'État et le point OSM."""
    station = parse_state_file(XML)[1]
    osm = _osm(42960018, 48.433395, -4.716160, ref="29810002", name="Station U", brand="Système U")
    assert link_to_osm(station, [osm]) == (osm, "ref_osm")


def test_a_single_station_very_close_without_identifier_is_linked_by_proximity():
    station = parse_state_file(XML)[0]
    osm = _osm(1, 48.34220, -4.72310, name="Intermarché")
    assert link_to_osm(station, [osm]) == (osm, "proximite")


def test_two_close_candidates_or_another_postcode_give_no_brand():
    station = parse_state_file(XML)[0]
    first, second = _osm(1, 48.34220, -4.72310, name="A"), _osm(2, 48.34190, -4.72290, name="B")
    assert link_to_osm(station, [first, second]) == (None, "aucun")
    elsewhere = _osm(3, 48.34220, -4.72310, name="C", postcode="29810")
    assert link_to_osm(station, [elsewhere]) == (None, "aucun")


def test_a_company_name_is_not_an_address():
    plougonvelin, plouarzel = parse_state_file(XML)
    assert usable_address(plougonvelin) == "RUE DU STADE, 29217 Plougonvelin"
    assert usable_address(plouarzel) is None


def test_the_shown_name_and_position_come_from_osm_the_rest_from_the_state():
    station = parse_state_file(XML)[1]
    osm = _osm(42960018, 48.433395, -4.716160, ref="29810002", name="Station U", brand="Système U")
    read_at = datetime(2026, 11, 7, 12, 0)
    rows = station_rows(station, osm, "ref_osm", read_at)
    assert rows["poi"] == {"name": "Station U", "latitude": 48.433395, "longitude": -4.716160, "address": None}
    assert rows["station"]["marque"] == "Système U"
    assert rows["station"]["adresse_etat"] == "SAS SNDL MENEZ CRENN"
    assert (rows["station"]["latitude_etat"], rows["station"]["lu_le"]) == (48.432, read_at)
    assert [p["carburant"] for p in rows["prix"]] == ["E10", "SP98"]


def test_without_osm_the_station_is_shown_at_the_state_position_under_a_generic_name():
    station = parse_state_file(XML)[0]
    rows = station_rows(station, None, "aucun", datetime(2026, 11, 7))
    assert rows["poi"]["name"] == DEFAULT_NAME
    assert (rows["poi"]["latitude"], rows["station"]["marque"]) == (48.342, None)


# --- Les stations douteuses (carte #180) ---

def _news(pdv_id, poi_id, lat, lon, last, name="Station-service"):
    return {"pdv_id": pdv_id, "poi_id": poi_id, "name": name, "address": None, "latitude": lat, "longitude": lon,
            "last_news": last}


NOW = datetime(2026, 11, 11, 21, 0)


def test_the_same_state_id_too_far_away_makes_a_doubtful_station():
    """Cas du Carrefour de Locmaria-Plouzané (9 nov.) : même identifiant de l'État dans OSM, mais à 1 096 m, donc douteux."""
    station = {"pdv_id": "29290003", "latitude": 48.3654, "longitude": -4.6428, "code_postal": "29280"}
    carrefour = _osm(1848473838, 48.3753, -4.6450, ref="29290003", name="Carrefour", brand="Carrefour")
    assert link_to_osm(station, [carrefour]) == (None, "aucun")
    [(signal, detail)] = link_signals(station, [carrefour])
    assert signal == "station_douteuse" and detail["osm_element"] == "node/1848473838"
    assert 1000 < detail["distance_m"] < 1200 and "identifiant" in detail["raison"]


def test_a_station_linked_close_by_is_not_doubtful():
    """Le même identifiant à 25 m (le Carrefour de Locmaria le 11 nov., position corrigée par l'État) : aucun doute."""
    station = {"pdv_id": "29290003", "latitude": 48.36541, "longitude": -4.64276, "code_postal": "29280"}
    assert link_signals(station, [_osm(1848473838, 48.3653, -4.64245, ref="29290003")]) == []


def test_last_news_counts_shortages_as_well_as_prices():
    """Une station de Quimper sans aucun prix déclare ses ruptures du jour : elle donne des nouvelles, elle est vivante."""
    prices = [{"releve_le": None, "rupture_debut": datetime(2022, 4, 19)},
              {"releve_le": None, "rupture_debut": datetime(2026, 11, 11, 16, 30)}]
    assert last_news(prices) == datetime(2026, 11, 11, 16, 30)
    assert last_news([{"releve_le": None, "rupture_debut": None}]) is None


def test_a_silent_station_next_to_an_active_one_is_a_twin():
    """Cas du Carrefour Contact de Plouguerneau : 29880005 muet depuis le 21 sept., 29880006 à 9 m déclare : un doublon."""
    old = _news("29880005", 48528, 48.60694, -4.51108, datetime(2026, 9, 21, 8, 43), "Carrefour Contact")
    new = _news("29880006", 48527, 48.607, -4.511, datetime(2026, 11, 9, 11, 13))
    signals = file_signals([old, new], [], NOW)
    assert signals["29880006"] == []
    [(signal, detail)] = signals["29880005"]
    assert signal == "doublon_station" and detail["autre_id"] == 48527 and detail["distance_m"] == 9
    assert "21/09/2026" in detail["raison"]


def test_a_silent_station_alone_may_have_closed():
    """Cas du Carrefour de Guilvinec : rien déclaré depuis 47 jours et aucune station active à côté : station muette."""
    guilvinec = _news("29730006", 48710, 47.8054, -4.2792, datetime(2026, 9, 25, 7, 0), "Carrefour")
    assert file_signals([guilvinec], [], NOW) == {
        "29730006": [("station_muette", {"raison": "rien déclaré à l'État depuis le 25/09/2026"})]}


def test_a_station_heard_of_recently_is_never_doubtful():
    """Une station qui a déclaré un prix ou une rupture dans les 30 derniers jours n'a rien à signaler."""
    assert file_signals([_news("29217001", 1, 48.342, -4.723, datetime(2026, 10, 20))], [], NOW) == {"29217001": []}


def test_two_silent_stations_side_by_side_are_not_twins():
    """Deux stations muettes voisines : aucune n'a les bons prix, chacune est muette, pas un doublon de l'autre."""
    a = _news("1", 1, 48.0, -4.0, datetime(2026, 9, 1))
    b = _news("2", 2, 48.00005, -4.0, datetime(2026, 9, 1))
    assert {signal for signals in file_signals([a, b], [], NOW).values() for signal, _ in signals} == {"station_muette"}


def test_a_station_missing_from_the_state_file_is_doubtful():
    """Le fichier de l'État n'a aucune fermeture : une station en base qui n'y est plus a peut-être fermé."""
    assert file_signals([], [{"pdv_id": "29000099"}], NOW)["29000099"][0][0] == "station_absente"
