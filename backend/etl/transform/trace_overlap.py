"""
Le recouvrement entre deux tracés de rando : quelle part du chemin ils ont en commun (issue #271).

Avant cette issue, un doublon n'était repéré qu'au nom du fichier : le même tracé, renommé, était chargé une seconde
fois. Cas réel du 19 novembre 2026, à Guidel : « Entre La Laita et Le Loch » a été chargé alors que « Entre Loch et
Laïta » était déjà en base. Les deux départs étaient à 2,8 km l'un de l'autre, et 89-90 % des points de chaque tracé
passaient à moins de 50 m de l'autre.

Le départ ne suffit donc pas : une même boucle peut commencer ailleurs, et deux randos du même parking peuvent
partir chacune de son côté. On compare donc les tracés entiers.

La méthode, en trois temps :
1. les points (latitude, longitude) sont mis en mètres, sur une petite carte plane autour du tracé ;
2. on ajoute des points tous les 20 m, pour qu'un tracé aux points espacés soit mesuré comme un tracé aux points
   serrés ;
3. on compte la part des points de A qui passent à moins de 50 m d'un point de B, puis l'inverse. On garde la plus
   petite des deux parts. Ainsi une petite boucle contenue dans une grande traversée (100 % dans un sens, 45 % dans
   l'autre, cas d'Orcines) n'est pas prise pour un doublon.

Mesure du 28 novembre 2026 sur les 1 085 tracés en base : les doublons se recouvrent à 86 % ou plus, et les randos
voisines à 75 % au plus (les deux GR de Pays d'Iroise, à Brest). Le seuil est posé à 85 %, entre les deux.
"""
import math

# Le rayon de la Terre, en mètres, pour passer des degrés aux mètres.
EARTH_RADIUS_M = 6371000.0
# L'écart entre deux points ajoutés le long du tracé.
POINT_SPACING_M = 20.0
# Un point passe « sur » l'autre tracé s'il est à moins de cette distance d'un de ses points (largeur d'un chemin,
# plus l'imprécision d'un GPS).
NEAR_DISTANCE_M = 50.0
# À partir de cette part en commun, dans les deux sens, deux tracés sont le même chemin : choix de l'utilisatrice
# du 28 novembre 2026, d'après la mesure sur les tracés en base.
DUPLICATE_SHARE = 0.85


def to_meters(points, reference_lat) -> list:
    """
    Met chaque point {"lat", "lon"} en coordonnées (x, y) en mètres. À l'échelle d'une rando, une carte plane suffit :
    un degré de longitude est plus court loin de l'équateur, d'où le cosinus de la latitude de référence.
    """
    shrink = math.cos(math.radians(reference_lat))
    return [(math.radians(p["lon"]) * EARTH_RADIUS_M * shrink, math.radians(p["lat"]) * EARTH_RADIUS_M)
            for p in points]


def add_points_along(points_xy) -> list:
    """Ajoute des points tous les 20 m entre deux points du tracé qui sont plus éloignés que cela."""
    if not points_xy:
        return []
    filled = [points_xy[0]]
    for (x1, y1), (x2, y2) in zip(points_xy, points_xy[1:]):
        gap = math.hypot(x2 - x1, y2 - y1)
        steps = int(gap // POINT_SPACING_M)
        for step in range(1, steps + 1):
            ratio = step * POINT_SPACING_M / gap
            filled.append((x1 + ratio * (x2 - x1), y1 + ratio * (y2 - y1)))
        filled.append((x2, y2))
    return filled


def cell_of(point_xy) -> tuple:
    """La case de 50 m sur 50 m où tombe un point."""
    return int(point_xy[0] // NEAR_DISTANCE_M), int(point_xy[1] // NEAR_DISTANCE_M)


def build_grid(points_xy) -> dict:
    """
    Range les points d'un tracé par case de 50 m. Pour savoir si un point a un voisin à moins de 50 m, il suffit
    alors de regarder sa case et les 8 cases autour, au lieu de tous les points du tracé.
    """
    grid = {}
    for point in points_xy:
        grid.setdefault(cell_of(point), []).append(point)
    return grid


def has_point_nearby(point_xy, grid) -> bool:
    """Dit si un point du tracé rangé dans `grid` est à moins de 50 m de ce point."""
    x, y = point_xy
    cell_x, cell_y = cell_of(point_xy)
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for other_x, other_y in grid.get((cell_x + dx, cell_y + dy), ()):
                if math.hypot(other_x - x, other_y - y) <= NEAR_DISTANCE_M:
                    return True
    return False


def share_near(points_xy, grid) -> float:
    """La part (de 0 à 1) des points de ce tracé qui passent à moins de 50 m de l'autre tracé."""
    if not points_xy:
        return 0.0
    near = sum(1 for point in points_xy if has_point_nearby(point, grid))
    return near / len(points_xy)


def overlap_share(points_a, points_b) -> float:
    """
    Le recouvrement de deux tracés, de 0 à 1 : la plus petite des deux parts, celle de A près de B et celle de B près
    de A. Les points sont des dictionnaires {"lat", "lon"}, comme dans le tracé lu du GPX et dans MongoDB.
    """
    if not points_a or not points_b:
        return 0.0
    reference_lat = points_a[0]["lat"]
    a_xy = add_points_along(to_meters(points_a, reference_lat))
    b_xy = add_points_along(to_meters(points_b, reference_lat))
    a_near_b = share_near(a_xy, build_grid(b_xy))
    b_near_a = share_near(b_xy, build_grid(a_xy))
    return min(a_near_b, b_near_a)


def is_same_path(points_a, points_b) -> bool:
    """Dit si deux tracés sont le même chemin : recouverts à 85 % ou plus, dans les deux sens."""
    return overlap_share(points_a, points_b) >= DUPLICATE_SHARE
