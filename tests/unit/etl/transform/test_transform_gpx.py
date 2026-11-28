import unicodedata

import pytest

from etl.transform import transform_gpx


def commune(name, insee) -> dict:
    """La commune que geo.api.gouv.fr donnerait au départ de la trace, avec son département et sa région."""
    return {"name": name, "insee": insee, "department": "Finistère", "region": "Bretagne"}


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


@pytest.fixture(autouse=True)
def nominatim_says_france(monkeypatch):
    """Sans réseau : Nominatim place le départ en France, sauf si un test dit autre chose (issue #272)."""
    monkeypatch.setattr(transform_gpx, "get_admin_info_from_coordinates",
                        lambda lat, lon: ("Finistère", "Bretagne", "France"))


def test_normalize_name_replaces_tokens() -> None:
    """Le numéro d'ordre devant le nom est retiré et l'apostrophe de « d_armor » remise."""
    assert transform_gpx.normalize_name("01-rando_test_d_armor") == "rando test d'armor"


@pytest.mark.parametrize("file_name, expected", [
    ("FFRandonnée-L_Île-d_Yeu___Kreuzland", "L'Île-d'Yeu : Kreuzland"),
    ("FFRandonnée-Dolus-d_Oléron___dunes_et_marais", "Dolus-d'Oléron : dunes et marais"),
    ("FFRandonnée-Pont-l_Abbé-d_Arnoult___au_bord_de_l_Arnoult", "Pont-l'Abbé-d'Arnoult : au bord de l'Arnoult"),
    ("FFRandonnée-Les_Sables-d_Olonne___Les_Bourbes", "Les Sables-d'Olonne : Les Bourbes"),
    ("FFRandonnée-Fouras___station_balnéaire,_presqu_île_ostréicole",
     "Fouras : station balnéaire, presqu'île ostréicole"),
    ("FFRandonnée-L_Épina", "L'Épina"),
])
def test_a_file_name_reads_with_its_apostrophes_and_separator(file_name, expected) -> None:
    """Le nom d'une rando tiré de son fichier retrouve ses apostrophes et son « : » (randos 349, 314, 351, 373, 315, 300 de l'import du 23 novembre)."""
    assert transform_gpx.normalize_name(file_name) == expected


def test_a_name_with_a_space_before_the_title_keeps_one_separator() -> None:
    """« L_Île-d_Yeu___ Kreuzland », avec un espace après les trois « _ », se lit aussi « L'Île-d'Yeu : Kreuzland »."""
    assert transform_gpx.normalize_name("L_Île-d_Yeu___ Kreuzland") == "L'Île-d'Yeu : Kreuzland"


def test_a_decomposed_accent_from_a_mac_file_name_is_recognized() -> None:
    """Un nom de fichier venu d'un Mac écrit « é » en deux caractères : le préfixe est quand même retiré, l'apostrophe remise."""
    decomposed = unicodedata.normalize("NFD", "FFRandonnée-L_Épina")

    assert transform_gpx.normalize_name(decomposed) == "L'Épina"


def test_a_name_with_a_hyphen_stays_whole() -> None:
    """Un nom de trace sans préfixe de source garde ce qui précède son premier tiret : « Saint-Pol… » ne devient pas « Pol… »."""
    assert transform_gpx.normalize_name("Saint-Pol-de-Léon par la côte") == "Saint-Pol-de-Léon par la côte"


def test_the_breton_ch_gets_its_apostrophe() -> None:
    """Le « c'h » breton retrouve son apostrophe : « Circuit_de_Roc_h_ar_Bic » se lit « Circuit de Roc'h ar Bic » (rando 22)."""
    assert transform_gpx.normalize_name("FFRandonnée-Circuit_de_Roc_h_ar_Bic") == "Circuit de Roc'h ar Bic"


def test_an_elision_before_a_consonant_keeps_its_apostrophe() -> None:
    """Un nom de lieu savoyard élide devant une consonne : « Praz_d_zeures » se lit « Praz d'zeures » (rando 605)."""
    file_name = "FFRandonnée-Refuge_de_Praz_d_zeures_en_2_jours_-_Itinéraire_pédestre"

    assert transform_gpx.normalize_name(file_name) == "Refuge de Praz d'zeures en 2 jours - Itinéraire pédestre"


def test_a_letter_inside_a_word_is_not_taken_for_an_elided_word() -> None:
    """Seul un petit mot isolé prend une apostrophe : « Rand_Abers » reste « Rand Abers » (rando 18)."""
    assert transform_gpx.normalize_name("FFRandonnée-Rand_Abers") == "Rand Abers"


def test_a_name_already_written_with_apostrophes_is_unchanged() -> None:
    """Un nom de trace déjà bien écrit, apostrophes comprises, ressort tel quel (« Refuge de Praz d'zeures »)."""
    name = "Refuge de Praz d'zeures en 2 jours - Itinéraire pédestre"

    assert transform_gpx.normalize_name(name) == name


def test_transform_gpx_returns_none_when_city_not_found(monkeypatch) -> None:
    monkeypatch.setattr(transform_gpx, "get_city_from_coordinates", lambda *args, **kwargs: None)
    monkeypatch.setattr(transform_gpx, "get_commune_at", lambda *args, **kwargs: None)

    result = transform_gpx.transform_gpx(GPX_SAMPLE, "trace.gpx")

    assert result is None


def test_transform_gpx_returns_expected_payload(monkeypatch) -> None:
    monkeypatch.setattr(transform_gpx, "get_city_from_coordinates", lambda *args, **kwargs: "Brest")
    monkeypatch.setattr(transform_gpx, "get_commune_at", lambda *args, **kwargs: commune("Brest", "29019"))

    result = transform_gpx.transform_gpx(GPX_SAMPLE, "trace.gpx")

    assert result is not None
    assert result["city_name"] == "Brest"
    assert result["name"] == "rando test d'armor"
    assert result["distance_km"] >= 1
    assert result["denivele_m"] == 100
    assert result["start_lat"] == 48.3904
    assert result["start_lon"] == -4.4861


def test_a_gpx_leaving_from_a_locality_is_named_after_its_commune(monkeypatch) -> None:
    """Un GPX qui part de la pointe de Corsen, que Nominatim range à Trézien, est rattaché à sa commune, Plouarzel."""
    monkeypatch.setattr(transform_gpx, "get_city_from_coordinates", lambda *args, **kwargs: "Trézien")
    monkeypatch.setattr(transform_gpx, "get_commune_at", lambda *args, **kwargs: commune("Plouarzel", "29177"))

    result = transform_gpx.transform_gpx(GPX_SAMPLE, "trace.gpx")

    assert (result["city_name"], result["commune"], result["insee"]) == ("Plouarzel", "Plouarzel", "29177")


def test_nominatim_names_the_city_only_when_the_state_does_not_answer(monkeypatch) -> None:
    """Sans réponse de geo.api.gouv.fr, le GPX garde le lieu donné par Nominatim plutôt que d'être perdu."""
    monkeypatch.setattr(transform_gpx, "get_city_from_coordinates", lambda *args, **kwargs: "Trézien")
    monkeypatch.setattr(transform_gpx, "get_commune_at", lambda *args, **kwargs: None)

    assert transform_gpx.transform_gpx(GPX_SAMPLE, "trace.gpx")["city_name"] == "Trézien"


def test_without_nominatim_the_city_is_named_after_its_commune(monkeypatch) -> None:
    monkeypatch.setattr(transform_gpx, "get_city_from_coordinates", lambda *args, **kwargs: None)
    monkeypatch.setattr(transform_gpx, "get_commune_at", lambda *args, **kwargs: commune("Plouarzel", "29177"))

    assert transform_gpx.transform_gpx(GPX_SAMPLE, "trace.gpx")["city_name"] == "Plouarzel"


def test_the_department_comes_with_the_commune_of_the_start(monkeypatch) -> None:
    """La commune du départ arrive avec son département et sa région : une ville nouvelle d'un envoi ne redemande pas l'État au chargement."""
    monkeypatch.setattr(transform_gpx, "get_city_from_coordinates", lambda *args, **kwargs: None)
    monkeypatch.setattr(transform_gpx, "get_commune_at", lambda *args, **kwargs: commune("Plouarzel", "29177"))

    assert transform_gpx.transform_gpx(GPX_SAMPLE, "trace.gpx")["commune_details"]["department"] == "Finistère"


def test_a_start_outside_france_is_marked_with_its_country(monkeypatch) -> None:
    """Un départ qu'aucune commune française ne contient, et que Nominatim place en Suisse, est marqué « hors de France » (cas de la Boucle d'Émosson, à Finhaut)."""
    monkeypatch.setattr(transform_gpx, "get_city_from_coordinates", lambda *args, **kwargs: "Finhaut")
    monkeypatch.setattr(transform_gpx, "get_commune_at", lambda *args, **kwargs: None)
    monkeypatch.setattr(transform_gpx, "get_admin_info_from_coordinates",
                        lambda lat, lon: ("Bas-Valais", "Valais", "Suisse"))

    result = transform_gpx.transform_gpx(GPX_SAMPLE, "Boucle d'Émosson.gpx")

    assert (result["city_name"], result["outside_france"]) == ("Finhaut", "Suisse")


def test_a_state_without_answer_does_not_mark_a_french_start(monkeypatch) -> None:
    """Si geo.api.gouv.fr ne répond pas, un départ que Nominatim place en France n'est pas marqué hors de France."""
    monkeypatch.setattr(transform_gpx, "get_city_from_coordinates", lambda *args, **kwargs: "Trézien")
    monkeypatch.setattr(transform_gpx, "get_commune_at", lambda *args, **kwargs: None)

    assert transform_gpx.transform_gpx(GPX_SAMPLE, "trace.gpx")["outside_france"] is None


def test_without_any_answer_no_country_is_guessed(monkeypatch) -> None:
    """Si ni l'État ni Nominatim ne disent le pays, on ne prévient de rien plutôt que de se tromper."""
    monkeypatch.setattr(transform_gpx, "get_city_from_coordinates", lambda *args, **kwargs: "Trézien")
    monkeypatch.setattr(transform_gpx, "get_commune_at", lambda *args, **kwargs: None)
    monkeypatch.setattr(transform_gpx, "get_admin_info_from_coordinates", lambda lat, lon: (None, None, None))

    assert transform_gpx.transform_gpx(GPX_SAMPLE, "trace.gpx")["outside_france"] is None


def test_a_french_commune_does_not_ask_nominatim_for_the_country(monkeypatch) -> None:
    """Un départ dans une commune française n'est pas marqué, et Nominatim n'est pas appelé pour le pays."""
    asked = []
    monkeypatch.setattr(transform_gpx, "get_city_from_coordinates", lambda *args, **kwargs: None)
    monkeypatch.setattr(transform_gpx, "get_commune_at", lambda *args, **kwargs: commune("Brest", "29019"))
    monkeypatch.setattr(transform_gpx, "get_admin_info_from_coordinates", lambda lat, lon: asked.append((lat, lon)))

    assert transform_gpx.transform_gpx(GPX_SAMPLE, "trace.gpx")["outside_france"] is None
    assert asked == []
