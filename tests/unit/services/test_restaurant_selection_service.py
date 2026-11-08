from datetime import date

from services.restaurant_selection_service import TABLE_CATEGORIES, TABLE_CATEGORY_LABELS, is_new, maps_url


def test_new_lasts_twelve_months():
    today = date(2026, 11, 4)
    assert is_new(date(2026, 6, 15), today)
    assert is_new(date(2025, 12, 1), today)
    assert not is_new(date(2025, 11, 1), today)
    assert not is_new(None, today)


def test_the_maps_link_searches_the_name_and_address():
    assert maps_url("L'Armen", "9 rue Lieutenant Jourden, 29217 Le Conquet") == (
        "https://www.google.com/maps/search/?api=1&query=L%27Armen+9+rue+Lieutenant+Jourden%2C+29217+Le+Conquet")
    assert maps_url("Riboul", None) == "https://www.google.com/maps/search/?api=1&query=Riboul"


def test_every_table_category_has_a_label_and_none_is_breton():
    assert list(TABLE_CATEGORY_LABELS) == TABLE_CATEGORIES
    assert "creperie" not in TABLE_CATEGORIES and "traditionnel" not in TABLE_CATEGORIES
