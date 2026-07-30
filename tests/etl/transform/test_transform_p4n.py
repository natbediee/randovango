from etl.transform.transform_p4n import parse_spot_name


def test_parse_spot_name_city_and_address() -> None:
    assert parse_spot_name("(29200) Brest - 172 Rue de Quimper") == ("29200", "Brest", "172 Rue de Quimper")


def test_parse_spot_name_place_without_city() -> None:
    # Sans tiret, ce qui suit le code postal est le nom du lieu, pas une commune.
    assert parse_spot_name("(29790) Camping Lizoé") == ("29790", None, "Camping Lizoé")


def test_parse_spot_name_empty_postal_code_and_address() -> None:
    assert parse_spot_name("() Poullaouen - ") == (None, "Poullaouen", None)
    # Même cas sans l'espace final : la commune ne doit pas devenir un lieu.
    assert parse_spot_name("() Poullaouen -") == (None, "Poullaouen", None)


def test_parse_spot_name_keeps_dashes_inside_address() -> None:
    assert parse_spot_name("(29800) Landerneau - Route de Saint-Thonan - parking bas") == (
        "29800",
        "Landerneau",
        "Route de Saint-Thonan - parking bas",
    )


def test_parse_spot_name_hyphenated_city_is_not_split() -> None:
    # Le séparateur est " - " (espaces inclus) : un trait d'union de commune ne compte pas.
    assert parse_spot_name("(29470) Plougastel-Daoulas - Le Passage") == (
        "29470",
        "Plougastel-Daoulas",
        "Le Passage",
    )


def test_parse_spot_name_without_template_falls_back_to_raw_name() -> None:
    assert parse_spot_name("Aire de la plage") == (None, None, "Aire de la plage")


def test_parse_spot_name_handles_empty_input() -> None:
    assert parse_spot_name(None) == (None, None, None)
    assert parse_spot_name("   ") == (None, None, None)
