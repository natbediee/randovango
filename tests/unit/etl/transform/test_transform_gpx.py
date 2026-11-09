from etl.transform import transform_gpx


GPX_SAMPLE = """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<gpx version=\"1.1\" creator=\"pytest\" xmlns=\"http://www.topografix.com/GPX/1/1\">
  <metadata>
    <name>Sample</name>
    <desc>Description test</desc>
  </metadata>
  <trk>
    <name>01-rando_test_d_armor</name>
    <trkseg>
      <trkpt lat=\"48.3904\" lon=\"-4.4861\"><ele>10</ele></trkpt>
      <trkpt lat=\"48.4000\" lon=\"-4.4800\"><ele>110</ele></trkpt>
    </trkseg>
  </trk>
</gpx>
"""


def test_normalize_name_replaces_tokens() -> None:
    assert transform_gpx.normalize_name("01-rando_test_d_armor") == "rando test d'armor"


def test_transform_gpx_returns_none_when_city_not_found(monkeypatch) -> None:
    monkeypatch.setattr(transform_gpx, "get_city_from_coordinates", lambda *args, **kwargs: None)
    monkeypatch.setattr(transform_gpx, "get_commune_from_coordinates", lambda *args, **kwargs: (None, None))

    result = transform_gpx.transform_gpx(GPX_SAMPLE, "trace.gpx")

    assert result is None


def test_transform_gpx_returns_expected_payload(monkeypatch) -> None:
    monkeypatch.setattr(transform_gpx, "get_city_from_coordinates", lambda *args, **kwargs: "Brest")
    monkeypatch.setattr(transform_gpx, "get_commune_from_coordinates", lambda *args, **kwargs: ("Brest", "29019"))

    result = transform_gpx.transform_gpx(GPX_SAMPLE, "trace.gpx")

    assert result is not None
    assert result["city_name"] == "Brest"
    assert result["name"] == "rando test d'armor"
    assert result["distance_km"] >= 1
    assert result["denivele_m"] == 100
    assert result["start_lat"] == 48.3904
    assert result["start_lon"] == -4.4861


def test_a_village_keeps_its_name_and_gets_its_commune(monkeypatch) -> None:
    # La pointe de Corsen : Nominatim dit Trézien, un village de Plouarzel.
    monkeypatch.setattr(transform_gpx, "get_city_from_coordinates", lambda *args, **kwargs: "Trézien")
    monkeypatch.setattr(transform_gpx, "get_commune_from_coordinates", lambda *args, **kwargs: ("Plouarzel", "29177"))

    result = transform_gpx.transform_gpx(GPX_SAMPLE, "trace.gpx")

    assert (result["city_name"], result["commune"], result["insee"]) == ("Trézien", "Plouarzel", "29177")


def test_without_nominatim_the_city_is_named_after_its_commune(monkeypatch) -> None:
    monkeypatch.setattr(transform_gpx, "get_city_from_coordinates", lambda *args, **kwargs: None)
    monkeypatch.setattr(transform_gpx, "get_commune_from_coordinates", lambda *args, **kwargs: ("Plouarzel", "29177"))

    assert transform_gpx.transform_gpx(GPX_SAMPLE, "trace.gpx")["city_name"] == "Plouarzel"
