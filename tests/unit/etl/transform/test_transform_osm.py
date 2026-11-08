from etl.transform.transform_osm import (months_open, normalize_osm_link, osm_link, osm_signals, pick_osm_element,
                                         transform_osm)


def test_transform_osm_filters_and_keeps_expected_pois() -> None:
    osm_json = {
        "elements": [
            {
                "type": "node",
                "id": 1,
                "lat": 48.39,
                "lon": -4.49,
                "tags": {"name": "Musee", "tourism": "museum"},
            },
            {
                "type": "node",
                "id": 2,
                "lat": 48.40,
                "lon": -4.50,
                "tags": {"name": "Point info", "tourism": "information"},
            },
            {
                "type": "node",
                "id": 3,
                "lat": 48.41,
                "lon": -4.51,
                "tags": {"name": "Office du tourisme", "tourism": "information"},
            },
            {
                "type": "way",
                "id": 4,
                "center": {"lat": 48.42, "lon": -4.52},
                "tags": {"natural": "beach", "name": "Plage test"},
            },
        ]
    }

    df = transform_osm(osm_json, city="Brest")

    assert len(df) == 3
    assert set(df["name"]) == {"Musee", "Office du tourisme", "Plage test"}
    assert set(df["type"]) == {"museum", "information", "beach"}


def test_transform_osm_invalid_payload_returns_empty_dataframe() -> None:
    df = transform_osm({}, city="Brest")

    assert df.empty


def test_transform_osm_keeps_breweries_tagged_as_craft() -> None:
    osm_json = {"elements": [{"type": "node", "id": 9, "lat": 48.5, "lon": -4.6,
                              "tags": {"name": "Brasserie des Abers", "craft": "brewery"}}]}
    df = transform_osm(osm_json, "Lannilis")
    assert df.iloc[0]["type"] == "brewery"


def test_transform_osm_reads_contact_website_and_details() -> None:
    osm_json = {"elements": [{
        "type": "node", "id": 5, "lat": 48.0, "lon": -4.0,
        "tags": {"name": "La Table", "amenity": "restaurant", "contact:website": "latable.fr",
                 "phone": "+33 2 98 00 00 00", "opening_hours": "Apr-Sep Mo-Su 12:00-22:00"},
    }]}

    row = transform_osm(osm_json, city="Brest").iloc[0]

    assert row["website"] == "https://latable.fr"
    assert row["osm_details"]["phone"] == "+33 2 98 00 00 00"
    assert row["osm_details"]["months_open"] == ["Apr", "May", "Jun", "Jul", "Aug", "Sep"]


def test_normalize_osm_link_completes_social_pages() -> None:
    assert normalize_osm_link("contact:facebook", "Aber-Wrach-1043") == "https://www.facebook.com/Aber-Wrach-1043"
    assert normalize_osm_link("contact:facebook", "https://100091272374097") == "https://www.facebook.com/100091272374097"
    assert normalize_osm_link("instagram", "@chezledu") == "https://www.instagram.com/chezledu"
    assert normalize_osm_link("contact:facebook", "https://www.facebook.com/x/") == "https://www.facebook.com/x/"


def test_osm_link_prefers_the_website_to_social_pages() -> None:
    assert osm_link({"contact:facebook": "x", "contact:website": "https://a.fr"}) == "https://a.fr"
    assert osm_link({"contact:facebook": "x"}) == "https://www.facebook.com/x"
    assert osm_link({}) is None


def test_months_open_only_when_part_of_the_year() -> None:
    assert months_open("Mar-Oct: Mo-Su 11:00-24:00") == ["Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct"]
    assert months_open("May 01-Sep 14 Mo-Su 11:00-23:00") == ["May", "Jun", "Jul", "Aug", "Sep"]
    assert months_open("Sep-Jun Tu-Sa 12:00-22:00; Jul-Aug Mo-Su 12:00-23:00") is None
    assert months_open("Mo-Su 12:00-22:00; Dec 25 off") is None
    assert months_open("Mo-Su 12:00-22:00") is None
    assert months_open(None) is None


POI = {"name": "La Table", "url": None}


def test_osm_signals_marks_closed_object() -> None:
    element = {"tags": {"disused:amenity": "restaurant"}}
    assert [signal for signal, _ in osm_signals(POI, element)] == ["fermeture_osm"]


def test_osm_signals_marks_closed_shop() -> None:
    assert [signal for signal, _ in osm_signals(POI, {"tags": {"disused:shop": "bakery"}})] == ["fermeture_osm"]


def test_osm_signals_ignores_history_of_an_open_restaurant() -> None:
    """La Rédac est bien un restaurant : was:shop=car raconte seulement ce qu'il y avait avant."""
    element = {"tags": {"amenity": "restaurant", "name": "La Table", "was:shop": "car"}}
    assert osm_signals(POI, element) == []


def test_osm_signals_marks_a_real_rename_only() -> None:
    renamed = {"tags": {"amenity": "restaurant", "name": "Le Maestro"}}
    spelling = {"tags": {"amenity": "restaurant", "name": "LA TABLE"}}
    old_name = {"tags": {"amenity": "restaurant", "name": "was:Autrefois"}}
    assert [signal for signal, _ in osm_signals(POI, renamed)] == ["renommage_osm"]
    assert osm_signals(POI, spelling) == []
    assert osm_signals(POI, old_name) == []


def test_osm_signals_proposes_a_link_only_when_missing() -> None:
    element = {"tags": {"amenity": "restaurant", "name": "La Table", "contact:website": "https://a.fr"}}
    assert osm_signals(POI, element) == [("lien_osm", {"url": "https://a.fr"})]
    assert osm_signals({**POI, "url": "https://b.fr"}, element) == []


def test_osm_signals_absent_object() -> None:
    assert osm_signals(POI, None)[0][0] == "absent_osm"


def test_pick_osm_element_refuses_a_distant_object() -> None:
    near = {"type": "way", "center": {"lat": 48.0, "lon": -4.0}}
    far = {"type": "node", "lat": 43.3, "lon": 5.4}
    assert pick_osm_element([far, near], 48.0, -4.0) is near
    assert pick_osm_element([far], 48.0, -4.0) is None


def test_an_unnamed_laundry_is_kept_with_its_operator() -> None:
    """Les deux laveries autour de Plougonvelin n'ont pas de nom dans OSM (7 novembre 2026) : elles n'étaient jamais chargées."""
    osm_json = {"elements": [{"type": "node", "id": 13110805364, "lat": 48.34, "lon": -4.72,
                              "tags": {"shop": "laundry", "operator": "Util", "self_service": "yes"}},
                             {"type": "node", "id": 1293779523, "lat": 48.36, "lon": -4.76, "tags": {"shop": "laundry"}},
                             {"type": "node", "id": 3, "lat": 48.36, "lon": -4.76, "tags": {"amenity": "toilets", "operator": "Mairie"}}]}
    df = transform_osm(osm_json, "Plougonvelin")
    assert list(df["name"]) == ["Laverie Util", "Laverie", "Toilettes publiques"]
