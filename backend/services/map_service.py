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
from pathlib import Path
from urllib.parse import urlparse

import fontawesomefree
from PIL import Image, ImageDraw, ImageFont

from utils.logger_util import LoggerUtil

logger = LoggerUtil.get_logger("map_service")

OSM_TILE_URL = "https://a.tile.openstreetmap.org/{z}/{x}/{y}.png"

# Un carnet demande une carte par jour + la carte générale, soit ~35 tuiles
# chacune : sans cache, un PDF déclenche plus de cent requêtes vers OSM, qui
# bride les clients gourmands. La génération pouvait alors dépasser les deux
# minutes et se faire couper par le proxy (504). Les tuiles étant quasi
# immuables, on les garde sur disque sans expiration (cf. nginx/randovango.conf
# pour le timeout côté proxy).
TILE_CACHE_DIR = Path(__file__).resolve().parents[2] / "storage" / "tile_cache"
# Une tuile répond normalement en quelques centaines de ms : au-delà, mieux vaut
# abandonner (staticmap réessaie) que bloquer le rendu du carnet.
TILE_REQUEST_TIMEOUT = 5
# La politique d'usage d'OSM impose un User-Agent identifiant l'application ;
# le défaut de staticmap ("StaticMap") est générique et se fait limiter.
TILE_HEADERS = {"User-Agent": "RandoVanGo/1.0 (carnet de voyage PDF)"}

FA_SOLID_TTF = os.path.join(
    os.path.dirname(fontawesomefree.__file__), "static", "fontawesomefree", "webfonts", "fa-solid-900.ttf"
)
# Police standard (chiffres lisibles) pour numéroter les étapes sur la carte de la rando -
# fa-solid-900.ttf est une police d'icônes, pas adaptée à l'affichage de chiffres.
DEJAVU_BOLD_TTF = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

# (couleur, glyphe Font Awesome solid, libellé) - mêmes couleurs/icônes que la carte Leaflet
# (POI_MARKER_STYLES dans frontend/static/js/map-helpers.js : les deux palettes
# doivent rester synchronisées, la carte du carnet rejouant celle du site).
# Palette de la charte RandoVanGo : teal pour le parcours (rando + spot), teintes
# naturelles désaturées pour les services, chaque catégorie restant distinguable
# de ses voisines. Le glyphe, lui, reste le repère principal sur la carte.
HIKE_STYLE = ("#2E7D86", "", "Randonnée")   # fa-hiking
SPOT_STYLE = ("#22424B", "", "Spot")  # fa-bed
DEFAULT_POI_STYLE = ("#7A8C89", "", "Service")  # fa-map-marker-alt

POI_CATEGORY_STYLES = {
    "eau":          ("#3D8EA8", "", "Eau potable"),       # fa-tint
    "vidange":      ("#5B7C99", "", "Vidange"),           # fa-recycle
    "gasoil":       ("#A3563C", "", "Carburant"),         # fa-gas-pump
    "supermarche":  ("#6E9A3C", "", "Supermarché"),       # fa-cart-arrow-down
    "commerce":     ("#9A6E3C", "", "Commerce"),          # fa-shopping-basket
    "restauration": ("#C58A2E", "", "Restauration"),      # fa-utensils
    "cafe":         ("#8C5A6E", "", "Café, bar"),         # fa-mug-hot
    "toilettes":    ("#6E8CA0", "", "Toilettes"),         # fa-toilet
    "hygiene":      ("#4FA3A0", "", "Hygiène / douche"),  # fa-shower
    "laverie":      ("#5E8F7A", "", "Laverie"),           # fa-shirt
    "culture":      ("#8A6BA1", "", "Culture / visite"),  # fa-camera
    "urgence":      ("#B04A4A", "", "Urgence"),           # fa-first-aid
}

# Les idées de Vany : pastille blanche bordée de sable avec son chapeau, comme
# .pepite-marker (frontend/static/css/app.css). Les lieux « En chemin », recommandés
# aussi par Vany : la même pastille en plus petit, comme .trail-tip-marker.
PEPITE_STYLE = ("#7A6224", "#ECDDB4", "Pépite de Vany")       # couleur de l'étiquette, bordure
HAT_PNG = Path(__file__).resolve().parents[1] / "assets" / "carnet" / "logo" / "hat-icon.png"

_icon_file_cache = {}


def fetch_hike_trace(mongo_id: str) -> list:
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


def _render_badge_png(size: int, background: str, outline: str = "white", glyph: str = None,
                      glyph_color: str = "white", picture: Path = None, label: str = None,
                      label_color: str = None) -> bytes:
    """
    Dessine une pastille ronde : une icône Font Awesome (`glyph`) ou une image
    (`picture`, le chapeau de Vany) au centre, et en option une étiquette (« J2 »)
    sous la pastille, comme sur la carte du site (buildDivIcon dans results.js).
    Le centre de la pastille reste à (largeur / 2, size / 2) : c'est le point
    d'ancrage du marqueur (voir _add_badge).
    """
    label_font = ImageFont.truetype(DEJAVU_BOLD_TTF, max(9, round(size * 0.34))) if label else None
    label_w = label_h = 0
    if label:
        bbox = label_font.getbbox(label)
        label_w, label_h = bbox[2] - bbox[0] + round(size * 0.3), bbox[3] - bbox[1] + round(size * 0.2)
    width = max(size, label_w)
    img = Image.new("RGBA", (width, size + (label_h + 2 if label else 0)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    left = (width - size) // 2
    draw.ellipse((left + 1, 1, left + size - 1, size - 1), fill=background, outline=outline, width=max(2, size // 15))
    if glyph:
        font = ImageFont.truetype(FA_SOLID_TTF, int(size * 0.45))
        bbox = draw.textbbox((0, 0), glyph, font=font)
        w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text((left + (size - w) / 2 - bbox[0], (size - h) / 2 - bbox[1]), glyph, font=font, fill=glyph_color)
    if picture:
        side = round(size * 0.6)
        hat = Image.open(picture).convert("RGBA")
        hat.thumbnail((side, side))
        img.alpha_composite(hat, (left + (size - hat.width) // 2, (size - hat.height) // 2))
    if label:
        top = size + 2
        x0 = (width - label_w) // 2
        draw.rounded_rectangle((x0, top, x0 + label_w - 1, top + label_h - 1), radius=3, fill=label_color or background)
        bbox = draw.textbbox((0, 0), label, font=label_font)
        draw.text((x0 + (label_w - (bbox[2] - bbox[0])) / 2 - bbox[0], top + (label_h - (bbox[3] - bbox[1])) / 2 - bbox[1]),
                  label, font=label_font, fill="white")
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


def _render_pin_png(color: str, glyph: str, size: int, label: str = None) -> bytes:
    """Pastille colorée avec l'icône Font Awesome en blanc (rando, spot, services)."""
    return _render_badge_png(size, color, glyph=glyph, label=label)


def _render_pepite_png(size: int, label: str = None) -> bytes:
    return _render_badge_png(size, "white", PEPITE_STYLE[1], picture=HAT_PNG, label=label,
                             label_color=PEPITE_STYLE[0])


def _render_trail_tip_png(size: int) -> bytes:
    return _render_badge_png(size, "white", PEPITE_STYLE[1], picture=HAT_PNG)


def _icon_file_path(key: tuple, render) -> str:
    """staticmap.IconMarker exige un chemin de fichier : on met en cache un fichier
    temporaire par marqueur (`key`) pour ne le dessiner qu'une seule fois."""
    if key not in _icon_file_cache:
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp.write(render())
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


def _tile_cache_path(url: str) -> Path:
    """Chemin de cache d'une tuile, nommé d'après ses coordonnées z/x/y."""
    return TILE_CACHE_DIR / ("_".join(urlparse(url).path.strip("/").split("/")[-3:]) or "tile.png")


_static_map_cls = None


def _static_map(width: int, height: int):
    """StaticMap configuré pour le carnet : tuiles OSM mises en cache sur disque,
    timeout par tuile et User-Agent identifiant. Importe staticmap à l'appel, les
    fonctions de rendu traitant son absence comme une carte simplement ignorée."""
    global _static_map_cls
    from staticmap import StaticMap

    if _static_map_cls is None:
        class CachedStaticMap(StaticMap):
            def get(self, url, **kwargs):
                path = _tile_cache_path(url)
                try:
                    return 200, path.read_bytes()
                except OSError:
                    pass
                status_code, content = super().get(url, **kwargs)
                if status_code == 200 and content:
                    try:
                        TILE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
                        # Écriture atomique : les tuiles sont téléchargées par
                        # plusieurs threads, un fichier tronqué serait relu tel quel.
                        tmp = path.with_suffix(f".{os.getpid()}.{id(content)}.tmp")
                        tmp.write_bytes(content)
                        tmp.replace(path)
                    except OSError as e:
                        logger.warning(f"[map] Tuile non mise en cache ({path.name}) : {e}")
                return status_code, content

        _static_map_cls = CachedStaticMap

    return _static_map_cls(
        width, height,
        url_template=OSM_TILE_URL,
        tile_request_timeout=TILE_REQUEST_TIMEOUT,
        headers=TILE_HEADERS,
    )


def _marker_scale(width: int, reference_width: int) -> float:
    """Facteur d'agrandissement des marqueurs et des tracés. Leurs tailles sont
    exprimées en pixels : sans cette mise à l'échelle, une carte rendue plus large
    (pour l'impression) afficherait des marqueurs proportionnellement plus petits."""
    return max(1.0, width / reference_width)


def render_hike_map_png(mongo_id: str, width: int = 700, height: int = 420, trail_tips: list = ()) -> bytes | None:
    """Carte dédiée à la rando (dissociée de la carte générale du jour) : uniquement
    le tracé, zoomé dessus, avec les étapes du GPX (waypoints) numérotées - les
    numéros renvoient à la liste d'indications sous la carte (cf. pdf_service.py) -
    et les lieux à voir en chemin (petit chapeau de Vany)."""
    try:
        from staticmap import CircleMarker, IconMarker, Line
    except ImportError:
        logger.warning("[map] Librairie staticmap non disponible, carte ignorée")
        return None

    trace_points = fetch_hike_trace(mongo_id)
    if len(trace_points) < 2:
        return None

    scale = _marker_scale(width, 700)
    m = _static_map(width, height)
    m.add_line(Line(trace_points, HIKE_STYLE[0], round(4 * scale)))

    # Les lieux « En chemin » d'abord, sous les étapes numérotées : les numéros
    # renvoient à l'itinéraire pas à pas et doivent rester lisibles. Le chapeau est
    # posé à côté du lieu (en haut à droite, comme un fanion), un point sable marquant
    # sa position exacte : centré dessus, il recouvrait l'étape voisine.
    tip_size = round(28 * scale)
    tip_path = _icon_file_path(("tip", tip_size), lambda: _render_trail_tip_png(tip_size))
    for tip in trail_tips or []:
        position = (tip["longitude"], tip["latitude"])
        m.add_marker(IconMarker(position, tip_path, -round(4 * scale), tip_size + round(4 * scale)))
        m.add_marker(CircleMarker(position, "white", round(9 * scale)))
        m.add_marker(CircleMarker(position, PEPITE_STYLE[0], round(6 * scale)))

    waypoints = fetch_hike_waypoints(mongo_id)
    pin_size = round(26 * scale)
    for i, wp in enumerate(waypoints, start=1):
        path = _numbered_pin_file_path(i, HIKE_STYLE[0], pin_size)
        m.add_marker(IconMarker((wp["lon"], wp["lat"]), path, pin_size // 2, pin_size // 2))

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
        from staticmap import IconMarker, Line
    except ImportError:
        logger.warning("[map] Librairie staticmap non disponible, carte ignorée")
        return None

    scale = _marker_scale(width, 900)
    m = _static_map(width, height)
    has_marker = False

    # Étiquette « J1 », « J2 »... sous les marqueurs, quand la carte montre plusieurs jours.
    several_days = len(days) > 1

    def add_badge(lon, lat, key, render, size):
        path = _icon_file_path(key, render)
        with Image.open(path) as image:
            width = image.width
        m.add_marker(IconMarker((lon, lat), path, width // 2, size // 2))

    def add_icon(lon, lat, color, glyph, size, label=None):
        size = round(size * scale)
        add_badge(lon, lat, ("pin", color, glyph, size, label),
                  lambda: _render_pin_png(color, glyph, size, label), size)

    for day in days:
        label = f"J{day['day_number']}" if several_days and day.get("day_number") else None
        if day.get("hike_id"):
            trace_points = fetch_hike_trace(day.get("hike_mongo_id"))
            if len(trace_points) >= 2:
                m.add_line(Line(trace_points, HIKE_STYLE[0], round(3 * scale)))
                has_marker = True
        if day.get("hike_latitude") and day.get("hike_longitude"):
            add_icon(day["hike_longitude"], day["hike_latitude"], *HIKE_STYLE[:2], 42, label)
            has_marker = True
        if day.get("spot_latitude") and day.get("spot_longitude"):
            add_icon(day["spot_longitude"], day["spot_latitude"], *SPOT_STYLE[:2], 42, label)
            has_marker = True
        for poi in day.get("pois") or []:
            if poi.get("latitude") and poi.get("longitude"):
                color, glyph, _ = POI_CATEGORY_STYLES.get(poi.get("category"), DEFAULT_POI_STYLE)
                add_icon(poi["longitude"], poi["latitude"], color, glyph, 32, label)
                has_marker = True
        # Les pépites ajoutées. Les lieux « En chemin » sont sur la carte de la rando
        # (render_hike_map_png), à l'échelle du tracé : ici, ils chargeaient la carte.
        pepite_size = round(38 * scale)
        for pepite in day.get("pepites") or []:
            add_badge(pepite["longitude"], pepite["latitude"], ("pepite", pepite_size, label),
                      lambda: _render_pepite_png(pepite_size, label), pepite_size)
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


LEGEND_ICON_SIZE = 18


def legend_entries(days: list) -> list:
    """Retourne les entrées de légende pertinentes pour ce voyage : la randonnée
    (le tracé, d'où une barre et non une pastille), le spot, puis les catégories
    de services effectivement utilisées.

    Chaque entrée est un dict {shape, color, label, icon_png} : `shape` vaut
    "bar" pour le tracé et "pin" pour les marqueurs, dont l'icône PNG reprend le
    marqueur exact posé sur la carte (glyphe compris, seul repère fiable là où
    deux catégories partagent une teinte proche)."""
    entries = [
        {"shape": "bar", "color": HIKE_STYLE[0], "label": HIKE_STYLE[2], "icon_png": None},
        {"shape": "pin", "color": SPOT_STYLE[0], "label": SPOT_STYLE[2],
         "icon_png": _render_pin_png(*SPOT_STYLE[:2], LEGEND_ICON_SIZE)},
    ]
    if any(day.get("pepites") for day in days):
        entries.append({"shape": "pin", "color": PEPITE_STYLE[0], "label": PEPITE_STYLE[2],
                        "icon_png": _render_pepite_png(LEGEND_ICON_SIZE)})
    seen_categories = set()
    for day in days:
        for poi in day.get("pois") or []:
            category = poi.get("category")
            if category and category not in seen_categories and category in POI_CATEGORY_STYLES:
                seen_categories.add(category)
                color, glyph, label = POI_CATEGORY_STYLES[category]
                entries.append({"shape": "pin", "color": color, "label": label,
                                "icon_png": _render_pin_png(color, glyph, LEGEND_ICON_SIZE)})
    return entries
