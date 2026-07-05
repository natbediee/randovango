from utils.geo_utils import get_bounding_box


def test_get_bounding_box_orders_bounds() -> None:
    min_lat, min_lon, max_lat, max_lon = get_bounding_box(48.39, -4.49, 10)

    assert min_lat < max_lat
    assert min_lon < max_lon


def test_get_bounding_box_zero_distance_returns_same_point() -> None:
    min_lat, min_lon, max_lat, max_lon = get_bounding_box(48.39, -4.49, 0)

    assert min_lat == max_lat == 48.39
    assert min_lon == max_lon == -4.49
