"""
Le recouvrement de deux tracés (issue #271) : le même chemin, renommé ou commencé ailleurs, est reconnu ; deux randos
voisines qui ne partagent que quelques tronçons ne sont pas confondues.

Les tracés sont dessinés à la main, en mètres autour d'un point de Guidel, puis mis en latitude et longitude.
"""
import math

from etl.transform import trace_overlap

ORIGIN_LAT, ORIGIN_LON = 47.79, -3.49


def to_lat_lon(points_m) -> list:
    """Met des points (x, y) en mètres, autour de l'origine, en points {"lat", "lon"}, comme ceux d'un GPX."""
    meters_per_degree = math.radians(1) * trace_overlap.EARTH_RADIUS_M
    shrink = math.cos(math.radians(ORIGIN_LAT))
    return [{"lat": ORIGIN_LAT + y / meters_per_degree, "lon": ORIGIN_LON + x / (meters_per_degree * shrink)}
            for x, y in points_m]


def path_through(corners, spacing=100) -> list:
    """Un tracé qui passe par ces coins (en mètres), avec un point tous les `spacing` mètres."""
    points = []
    for (x1, y1), (x2, y2) in zip(corners, corners[1:]):
        steps = max(1, int(math.hypot(x2 - x1, y2 - y1) // spacing))
        points += [(x1 + (x2 - x1) * k / steps, y1 + (y2 - y1) * k / steps) for k in range(steps)]
    points.append(corners[-1])
    return points


# Une boucle carrée de 4 km : 1 km de côté.
LOOP = [(0, 0), (1000, 0), (1000, 1000), (0, 1000), (0, 0)]


def test_the_same_loop_started_elsewhere_is_the_same_path() -> None:
    """La même boucle, commencée de l'autre côté et aux points plus espacés, est le même chemin (cas de Guidel)."""
    loop = to_lat_lon(path_through(LOOP))
    started_elsewhere = to_lat_lon(path_through([(1000, 1000), (0, 1000), (0, 0), (1000, 0), (1000, 1000)], 300))

    assert trace_overlap.overlap_share(loop, started_elsewhere) == 1.0
    assert trace_overlap.is_same_path(loop, started_elsewhere)


def test_a_gps_gap_of_a_few_meters_keeps_the_same_path() -> None:
    """Le même chemin enregistré par un autre GPS, décalé de 20 m, reste le même chemin (cas du Gouet Nord)."""
    loop = to_lat_lon(path_through(LOOP))
    shifted = to_lat_lon([(x + 20, y) for x, y in path_through(LOOP)])

    assert trace_overlap.is_same_path(loop, shifted)


def test_neighbour_hikes_sharing_one_side_are_not_confused() -> None:
    """Deux boucles voisines qui ne partagent qu'un côté sur quatre ne sont pas confondues."""
    loop = to_lat_lon(path_through(LOOP))
    neighbour = to_lat_lon(path_through([(1000, 0), (2000, 0), (2000, 1000), (1000, 1000), (1000, 0)]))

    assert trace_overlap.overlap_share(loop, neighbour) < 0.4
    assert not trace_overlap.is_same_path(loop, neighbour)


def test_a_variant_sharing_three_quarters_is_not_the_same_path() -> None:
    """Une variante qui partage les trois quarts du chemin reste une autre rando (cas des deux GR d'Iroise, 75 %)."""
    loop = to_lat_lon(path_through(LOOP))
    variant = to_lat_lon(path_through([(0, 0), (1000, 0), (1000, 1000), (0, 1000), (-400, 500), (0, 0)]))

    assert not trace_overlap.is_same_path(loop, variant)


def test_a_short_hike_inside_a_long_one_is_not_the_same_path() -> None:
    """Une petite rando entièrement comprise dans une grande traversée n'est pas un doublon (cas d'Orcines)."""
    crossing = to_lat_lon(path_through([(0, 0), (10000, 0)]))
    short_part = to_lat_lon(path_through([(0, 0), (4000, 0)]))

    assert trace_overlap.overlap_share(crossing, short_part) < 0.5
    assert not trace_overlap.is_same_path(crossing, short_part)


def test_a_trace_without_points_overlaps_nothing() -> None:
    """Un tracé sans aucun point ne recouvre rien."""
    loop = to_lat_lon(path_through(LOOP))

    assert trace_overlap.overlap_share(loop, []) == 0.0
