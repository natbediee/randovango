"""
Génération d'une carte statique (image PNG) du voyage pour le carnet PDF
(voir backend/services/pdf_service.py). WeasyPrint ne peut pas exécuter le
JS de Leaflet utilisé sur la page /results : on recompose donc une carte
raster à partir des mêmes tuiles OpenStreetMap, avec des marqueurs qui
reprennent les mêmes couleurs et icônes Font Awesome que la carte interactive
(cf. HIKE_STYLE/SPOT_STYLE/POI_MARKER_STYLES dans
frontend/templates/pages/results.html). La police est fournie par le paquet
pip `fontawesomefree`, qui embarque les mêmes fichiers que le webfont chargé
par CDN sur le site (même version 6.4.0).
"""
import os
import tempfile
from io import BytesIO

import fontawesomefree
from PIL import Image, ImageDraw, ImageFont

from utils.logger_util import LoggerUtil

logger = LoggerUtil.get_logger("map_service")

OSM_TILE_URL = "https://a.tile.openstreetmap.org/{z}/{x}/{y}.png"

FA_SOLID_TTF = os.path.join(
    os.path.dirname(fontawesomefree.__file__), "static", "fontawesomefree", "webfonts", "fa-solid-900.ttf"
)
# Police standard (chiffres lisibles) pour numéroter les étapes sur la carte de la rando —
# fa-solid-900.ttf est une police d'icônes, pas adaptée à l'affichage de chiffres.
DEJAVU_BOLD_TTF = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

# (couleur, glyphe Font Awesome solid, libellé) — mêmes couleurs/icônes que la carte Leaflet
HIKE_STYLE = ("#4B6F8E", "", "Randonnée")   # fa-hiking
SPOT_STYLE = ("#26C6A6", "", "Spot")  # fa-bed
DEFAULT_POI_STYLE = ("#9E9E9E", "", "Service")  # fa-map-marker-alt

POI_CATEGORY_STYLES = {
    "eau":          ("#E91E63", "", "Eau potable"),       # fa-tint
    "vidange":      ("#EE3575", "", "Vidange"),           # fa-recycle
    "gasoil":       ("#F24D89", "", "Carburant"),         # fa-gas-pump
    "supermarche":  ("#F5659C", "", "Supermarché"),       # fa-cart-arrow-down
    "commerce":     ("#F77DB0", "", "Commerce"),          # fa-shopping-basket
    "restauration": ("#F990C1", "", "Restauration"),      # fa-utensils
    "toilettes":    ("#FAA5CE", "", "Toilettes"),         # fa-toilet
    "hygiene":      ("#FBBAD9", "", "Hygiène / douche"),  # fa-shower
    "culture":      ("#FCCFE5", "", "Culture / visite"),  # fa-camera
    "urgence":      ("#FDE3F0", "", "Urgence"),           # fa-first-aid
}

_icon_file_cache = {}


def _fetch_hike_trace(mongo_id: str) -> list:
    """Récupère les points [lon, lat] du tracé GPX depuis MongoDB (même source que
    la route /api/step2/hike/{id}/trace utilisée par la carte interactive)."""
    if not mongo_id:
        return []
    from utils.mongo_utils import MongoUtils
    from bson import ObjectId
    try:
        MongoUtils.connect()
        doc = MongoUtils.get_collection("gpx_traces").find_one({"_id": ObjectId(mongo_id)})
        MongoUtils.disconnect()
        if not doc or not doc.get("points"):
            return []
        return [(p["lon"], p["lat"]) for p in doc["points"]]
    except Exception as e:
        logger.warning(f"[map] Échec récupération tracé GPX ({mongo_id}) : {e}")
        return []


def fetch_hike_waypoints(mongo_id: str) -> list:
    """Récupère les étapes/indications (waypoints nommés avec description) du
    tracé GPX depuis MongoDB : données extraites du GPX à l'import mais jamais
    exploitées jusqu'ici (ni sur le site, ni dans le PDF)."""
    if not mongo_id:
        return []
    from utils.mongo_utils import MongoUtils
    from bson import ObjectId
    try:
        MongoUtils.connect()
        doc = MongoUtils.get_collection("gpx_traces").find_one({"_id": ObjectId(mongo_id)})
        MongoUtils.disconnect()
        if not doc:
            return []
        raw = [wp for wp in (doc.get("waypoints") or []) if wp.get("lat") and wp.get("lon")]
        # Déduplique (nom, lat, lon) : certaines randos importées avant la correction
        # de transform_gpx.py ont chaque étape enregistrée deux fois en base.
        seen = set()
        waypoints = []
        for wp in raw:
            key = (wp.get("name"), wp["lat"], wp["lon"])
            if key in seen:
                continue
            seen.add(key)
            waypoints.append(wp)
        return waypoints
    except Exception as e:
        logger.warning(f"[map] Échec récupération waypoints GPX ({mongo_id}) : {e}")
        return []


def _render_pin_png(color: str, glyph: str, size: int) -> bytes:
    """Dessine un badge rond coloré avec l'icône Font Awesome centrée en blanc."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((1, 1, size - 1, size - 1), fill=color, outline="white", width=max(2, size // 15))
    font = ImageFont.truetype(FA_SOLID_TTF, int(size * 0.45))
    bbox = draw.textbbox((0, 0), glyph, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((size - w) / 2 - bbox[0], (size - h) / 2 - bbox[1]), glyph, font=font, fill="white")
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


def _icon_file_path(color: str, glyph: str, size: int) -> str:
    """staticmap.IconMarker exige un chemin de fichier : on met en cache un fichier
    temporaire par (couleur, glyphe, taille) pour ne le dessiner qu'une seule fois."""
    key = (color, glyph, size)
    if key not in _icon_file_cache:
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp.write(_render_pin_png(color, glyph, size))
        tmp.close()
        _icon_file_cache[key] = tmp.name
    return _icon_file_cache[key]


_numbered_pin_cache = {}


def _render_numbered_pin_png(number: int, color: str, size: int) -> bytes:
    """Dessine un badge rond coloré avec le numéro de l'étape, pour repérer les
    waypoints du GPX sur la carte dédiée à la rando."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((1, 1, size - 1, size - 1), fill=color, outline="white", width=max(2, size // 15))
    label = str(number)
    font = ImageFont.truetype(DEJAVU_BOLD_TTF, int(size * 0.5))
    bbox = draw.textbbox((0, 0), label, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((size - w) / 2 - bbox[0], (size - h) / 2 - bbox[1]), label, font=font, fill="white")
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


def _numbered_pin_file_path(number: int, color: str, size: int) -> str:
    key = (number, color, size)
    if key not in _numbered_pin_cache:
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp.write(_render_numbered_pin_png(number, color, size))
        tmp.close()
        _numbered_pin_cache[key] = tmp.name
    return _numbered_pin_cache[key]


def render_hike_map_png(mongo_id: str, width: int = 700, height: int = 420) -> bytes | None:
    """Carte dédiée à la rando (dissociée de la carte générale du jour) : uniquement
    le tracé, zoomé dessus, avec les étapes du GPX (waypoints) numérotées — les
    numéros renvoient à la liste d'indications sous la carte (cf. pdf_service.py)."""
    try:
        from staticmap import StaticMap, IconMarker, Line
    except ImportError:
        logger.warning("[map] Librairie staticmap non disponible, carte ignorée")
        return None

    trace_points = _fetch_hike_trace(mongo_id)
    if len(trace_points) < 2:
        return None

    m = StaticMap(width, height, url_template=OSM_TILE_URL)
    m.add_line(Line(trace_points, HIKE_STYLE[0], 4))

    waypoints = fetch_hike_waypoints(mongo_id)
    for i, wp in enumerate(waypoints, start=1):
        path = _numbered_pin_file_path(i, HIKE_STYLE[0], 26)
        m.add_marker(IconMarker((wp["lon"], wp["lat"]), path, 13, 13))

    try:
        image = m.render()
    except Exception as e:
        logger.warning(f"[map] Échec de génération de la carte rando : {e}")
        return None

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def render_overview_map_png(days: list, width: int = 900, height: int = 550) -> bytes | None:
    """Construit une carte regroupant les points d'un ou plusieurs jours (randos,
    spots, services), avec des marqueurs identiques (couleur + icône) à ceux de
    la carte interactive. Appelée avec une liste d'un seul jour pour une carte
    par jour dans le PDF. Retourne None si aucune coordonnée n'est disponible,
    ou si la génération échoue (ex: pas d'accès réseau vers les tuiles OSM)."""
    try:
        from staticmap import StaticMap, IconMarker, Line
    except ImportError:
        logger.warning("[map] Librairie staticmap non disponible, carte ignorée")
        return None

    m = StaticMap(width, height, url_template=OSM_TILE_URL)
    has_marker = False

    def add_icon(lon, lat, color, glyph, size):
        path = _icon_file_path(color, glyph, size)
        m.add_marker(IconMarker((lon, lat), path, size // 2, size // 2))

    for day in days:
        if day.get("hike_id"):
            trace_points = _fetch_hike_trace(day.get("hike_mongo_id"))
            if len(trace_points) >= 2:
                m.add_line(Line(trace_points, HIKE_STYLE[0], 3))
                has_marker = True
        if day.get("hike_latitude") and day.get("hike_longitude"):
            add_icon(day["hike_longitude"], day["hike_latitude"], *HIKE_STYLE[:2], 42)
            has_marker = True
        if day.get("spot_latitude") and day.get("spot_longitude"):
            add_icon(day["spot_longitude"], day["spot_latitude"], *SPOT_STYLE[:2], 42)
            has_marker = True
        for poi in day.get("pois") or []:
            if poi.get("latitude") and poi.get("longitude"):
                color, glyph, _ = POI_CATEGORY_STYLES.get(poi.get("category"), DEFAULT_POI_STYLE)
                add_icon(poi["longitude"], poi["latitude"], color, glyph, 32)
                has_marker = True

    if not has_marker:
        return None

    try:
        image = m.render()
    except Exception as e:
        logger.warning(f"[map] Échec de génération de la carte statique : {e}")
        return None

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def legend_entries(days: list) -> list:
    """Retourne les entrées de légende (icône PNG, libellé) pertinentes pour ce
    voyage : Randonnée/Spot toujours présents, puis les catégories de
    services effectivement utilisées."""
    entries = [
        (_render_pin_png(*HIKE_STYLE[:2], 28), HIKE_STYLE[2]),
        (_render_pin_png(*SPOT_STYLE[:2], 28), SPOT_STYLE[2]),
    ]
    seen_categories = set()
    for day in days:
        for poi in day.get("pois") or []:
            category = poi.get("category")
            if category and category not in seen_categories and category in POI_CATEGORY_STYLES:
                seen_categories.add(category)
                color, glyph, label = POI_CATEGORY_STYLES[category]
                entries.append((_render_pin_png(color, glyph, 28), label))
    return entries
