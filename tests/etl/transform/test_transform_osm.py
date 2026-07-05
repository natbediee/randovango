from etl.transform.transform_osm import transform_osm


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
