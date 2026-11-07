from datetime import date

from services.restaurant_selection_service import is_out_of_season, season_label


def test_the_season_label_reads_the_months():
    assert season_label("confirmee", "[3, 4, 5, 6, 7, 8, 9]") == "Ouvert d'avril à octobre"
    assert season_label("confirmee", [2, 3, 4]) == "Ouvert de mars à mai"


def test_a_season_across_the_new_year_starts_after_the_closed_months():
    assert season_label("confirmee", [10, 11, 0, 1]) == "Ouvert de novembre à février"
    assert not is_out_of_season("confirmee", [10, 11, 0, 1], date(2027, 1, 15))
    assert is_out_of_season("confirmee", [10, 11, 0, 1], date(2027, 6, 15))


def test_only_a_confirmed_season_with_months_hides_a_place():
    assert not is_out_of_season("probable", None, date(2026, 11, 7))
    assert not is_out_of_season("confirmee", None, date(2026, 11, 7))
    assert not is_out_of_season(None, "[6, 7]", date(2026, 11, 7))


def test_a_place_open_all_year_or_not_seasonal_has_no_label():
    assert season_label("confirmee", list(range(12))) is None
    assert season_label(None, None) is None
    assert season_label("probable", None) == "Saisonnier, vérifie l'ouverture"
