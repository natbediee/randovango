"""
Construction du HTML du carnet de voyage, converti en PDF par WeasyPrint
(voir backend/api/routers/result.py, route GET /api/result/pdf).

Le gabarit suit la charte RandoVanGo (crème/menthe/teal, Archivo + Public Sans,
mascotte Vany) définie dans design_handoff_carnet_pdf/. Structure du document :
couverture (titre, totaux du séjour, carte de l'itinéraire), puis une page par
jour (randonnée, spot pour la nuit, services), puis la clôture (mot de Vany).
"""
import base64
import re
from datetime import date, timedelta
from functools import lru_cache
from html import escape
from pathlib import Path

from services.map_service import (
    POI_CATEGORY_STYLES,
    DEFAULT_POI_STYLE,
    render_overview_map_png,
    render_hike_map_png,
    fetch_hike_waypoints,
    legend_entries,
)

# --- Palette (design tokens du handoff) ------------------------------------
CREAM = "#F9F8F1"
INK = "#22424B"
BODY = "#3C5457"
MUTED = "#64797C"
TERTIARY = "#7A8C89"
FOOTER_GREY = "#9AA6A0"
TEAL = "#2E7D86"
MINT = "#E6F3F0"
MINT_BORDER = "#C9E4DD"
MINT_BORDER_2 = "#A9DCD3"
NEUTRAL_BORDER = "#E8E6DB"
SEPARATOR = "#F0EEE3"
STAR = "#C99A2E"

# Badge de difficulté : fond / bordure / texte
DIFFICULTY_BADGES = {
    "facile":   ("#F1F7E0", "#D5E5A8", "#5F7A24"),
    "moyen":    ("#FBF3DE", "#ECDDB4", "#9A7A2E"),
    "difficile": ("#F6E7E0", "#E7C6B4", "#A34E2A"),
}

# Mascottes et logo du carnet, embarqués dans le backend (assets/carnet/) plutôt
# que lus dans frontend/static/ : en Docker le conteneur backend ne monte que le
# dossier backend, un chemin traversant le repo vers frontend/ n'existe pas là.
CARNET_ASSETS = Path(__file__).resolve().parents[1] / "assets" / "carnet"

# Dimensions de rendu des cartes (pixels de l'image PNG). La zone de contenu d'une
# page A4 à marge 0.55in fait ~688px CSS de large : on rend les cartes à 2x pour
# qu'elles restent nettes à l'impression. Le ratio de la carte d'itinéraire est
# celui du gabarit (688 x 262) ; celle d'une rando est plus haute, un tracé formant
# souvent une boucle.
OVERVIEW_MAP_PX = (1376, 524)
HIKE_MAP_PX = (1376, 840)

FR_WEEKDAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
FR_MONTHS = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]


# ---------------------------------------------------------------------------
# Formatage français
# ---------------------------------------------------------------------------

def _fr_number(value, decimals=0) -> str:
    """Nombre à la française : séparateur de milliers en espace insécable (U+00A0,
    pour que "1 072 m" ne se coupe pas en fin de ligne) et virgule décimale
    (1072 → "1 072", 3.0 avec decimals=1 → "3,0")."""
    if value is None:
        return ""
    text = f"{float(value):,.{decimals}f}".replace(",", " ").replace(".", ",")
    return text


def _fr_int(value) -> str:
    """Nombre entier à la française, sans décimale superflue (13.0 → "13")."""
    if value is None:
        return ""
    return _fr_number(round(float(value)))


def _fr_measure(value) -> str:
    """Mesure lisible : entier tant qu'elle en est un, sinon une décimale
    (13.0 → "13", 13.5 → "13,5")."""
    if value is None:
        return ""
    number = float(value)
    if number == int(number):
        return _fr_int(number)
    return _fr_number(number, 1)


def _long_date(day: date, weekday: bool = True) -> str:
    """Date en toutes lettres : "mercredi 15 juillet 2026" (le jour de la semaine
    situe une journée du séjour, mais n'apporte rien à une date d'édition)."""
    prefix = f"{FR_WEEKDAYS[day.weekday()]} " if weekday else ""
    return f"{prefix}{day.day} {FR_MONTHS[day.month - 1]} {day.year}"


def _day_date_label(start_date, day_number) -> str:
    if not start_date:
        return ""
    try:
        return _long_date(start_date + timedelta(days=day_number - 1))
    except TypeError:
        return ""


def _plural(count, singular, plural=None) -> str:
    return f"{count} {singular if count <= 1 else (plural or singular + 's')}"


# ---------------------------------------------------------------------------
# Images (inlinées en base64 : WeasyPrint reçoit le HTML sans base_url)
# ---------------------------------------------------------------------------

def _data_uri(png_bytes: bytes) -> str:
    return f"data:image/png;base64,{base64.b64encode(png_bytes).decode('ascii')}"


@lru_cache(maxsize=8)
def _asset_data_uri(*relative_parts: str) -> str:
    """Data URI d'un asset du carnet (assets/carnet/), mis en cache : les mascottes
    pèsent quelques centaines de Ko et sont relues à chaque carnet sinon."""
    return _data_uri((CARNET_ASSETS.joinpath(*relative_parts)).read_bytes())


# ---------------------------------------------------------------------------
# Feuille de style
# ---------------------------------------------------------------------------

CSS = f"""
@import url('https://fonts.googleapis.com/css2?family=Archivo:wght@600;700;800&family=Public+Sans:wght@400;600;700;800&display=swap');

@page {{
    size: A4 portrait;
    margin: 0.55in;
    background: {CREAM};
}}
* {{ box-sizing: border-box; -weasy-print-color-adjust: exact; print-color-adjust: exact; }}
body {{
    margin: 0;
    font-family: 'Public Sans', system-ui, sans-serif;
    color: {INK};
    font-size: 13.5px;
    line-height: 1.5;
}}
p {{ margin: 0; text-wrap: pretty; }}
a {{ color: {TEAL}; text-decoration: none; }}

/* --- Lockup logo : texte Archivo, chapeau posé sur le « n » (jamais une image
   plate : le logo doit rester du texte net et sélectionnable). --- */
.lockup {{
    font-family: 'Archivo', system-ui, sans-serif;
    font-weight: 800;
    font-size: 23px;
    letter-spacing: -0.4px;
    color: {INK};
}}
.lockup__teal {{ color: {TEAL}; }}
.lockup__n {{ color: {TEAL}; position: relative; display: inline-block; }}
.lockup__hat {{
    position: absolute;
    width: 1.05em;
    top: -0.6em;
    left: 50%;
    transform: translateX(-56%);
}}

/* --- Couverture --- */
.cover-head {{
    display: flex;
    align-items: center;
    justify-content: space-between;
}}
.cover-head__date {{ font-family: ui-monospace, Menlo, monospace; font-size: 11px; color: {TERTIARY}; letter-spacing: 0.2px; }}
.rule {{ height: 1px; background: {NEUTRAL_BORDER}; margin: 14px 0 26px; }}

.hero {{ display: flex; align-items: center; justify-content: space-between; gap: 22px; }}
.hero__text {{ flex: 1; }}
.hero__eyebrow {{
    display: block;
    font-size: 11.5px;
    font-weight: 800;
    letter-spacing: 2.5px;
    text-transform: uppercase;
    color: {TEAL};
    margin-bottom: 12px;
}}
.hero__title {{
    font-family: 'Archivo', system-ui, sans-serif;
    font-weight: 800;
    font-size: 44px;
    line-height: 1.02;
    letter-spacing: -1px;
    margin-bottom: 12px;
}}
.hero__subtitle {{ font-size: 15.5px; line-height: 1.5; color: {MUTED}; max-width: 440px; }}
.hero__vany {{ width: 150px; }}

/* Les pilules et badges bordés sont en inline-block : sur un <span> inline,
   WeasyPrint applique le line-height du corps (1.5) à la boîte de ligne et
   dessine alors la bordure arrondie deux fois (un liseré fantôme autour de la
   capsule). inline-block fixe la boîte et supprime ce doublon. */
.pills {{ display: flex; flex-wrap: wrap; gap: 9px; margin-top: 22px; }}
.pill {{
    display: inline-block;
    font-size: 12.5px;
    font-weight: 600;
    color: {INK};
    background: #FFFFFF;
    border: 1px solid {MINT_BORDER};
    border-radius: 999px;
    padding: 6px 14px;
}}

/* --- Cartes (couverture et randonnée) --- */
.map-card {{
    margin-top: 26px;
    border: 1px solid {NEUTRAL_BORDER};
    border-radius: 16px;
    background: #FFFFFF;
    break-inside: avoid;
}}
/* Le radius est répété sur l'image : WeasyPrint ne rogne pas l'enfant d'un
   conteneur en overflow:hidden, les angles de la carte dépasseraient sinon. */
.map-card__img {{ display: block; width: 100%; border-radius: 16px 16px 0 0; }}
.map-legend {{
    display: flex;
    flex-wrap: wrap;
    gap: 14px 22px;
    padding: 15px 20px;
    border-top: 1px solid {SEPARATOR};
}}
.legend-item {{ display: flex; align-items: center; gap: 8px; font-size: 12.5px; font-weight: 600; color: {BODY}; }}
/* display:block sur les span décoratifs vides (filets, barres, pastilles) : en
   inline, WeasyPrint leur dessine en plus le strut de la ligne, qui apparaît
   comme un petit trait vertical parasite à côté de la forme. */
.legend-bar {{ display: block; width: 22px; height: 4px; border-radius: 2px; background: {TEAL}; }}
.legend-pin {{ display: block; width: 18px; height: 18px; }}

/* --- En-tête de jour --- */
.day {{ break-before: page; }}
.day-header {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    padding-bottom: 14px;
    border-bottom: 2px solid {INK};
    margin-bottom: 22px;
}}
/* flex:none : sans cela WeasyPrint réduit le bloc au minimum et coupe le nom de
   ville sur deux lignes alors que la place ne manque pas. */
.day-header__left {{ display: flex; align-items: center; gap: 13px; flex: none; }}
/* white-space:nowrap sur les éléments de l'en-tête : WeasyPrint sous-estime la
   largeur des flex items et couperait « Jour 1 » ou le nom de ville sur deux
   lignes alors que la place ne manque pas. */
.day-badge {{
    background: {INK};
    color: {CREAM};
    font-family: 'Archivo', system-ui, sans-serif;
    font-weight: 800;
    font-size: 13px;
    padding: 6px 12px;
    border-radius: 7px;
    letter-spacing: 0.3px;
    white-space: nowrap;
}}
.day-city {{
    font-family: 'Archivo', system-ui, sans-serif;
    font-weight: 800;
    font-size: 24px;
    letter-spacing: -0.5px;
    white-space: nowrap;
}}
.day-date {{ font-family: ui-monospace, Menlo, monospace; font-size: 12px; color: {MUTED}; }}

/* --- Sur-titres de section (« RANDONNÉE DU JOUR ») --- */
.section-head {{ display: flex; align-items: center; gap: 10px; margin-bottom: 9px; }}
.eyebrow {{
    font-size: 11px;
    font-weight: 800;
    letter-spacing: 2px;
    text-transform: uppercase;
    color: {TEAL};
}}
.section-head__rule {{ display: block; height: 1px; flex: 1; background: {NEUTRAL_BORDER}; }}
.section-head__rule--soft {{ background: {SEPARATOR}; }}
.verified-badge {{
    display: inline-block;
    font-size: 11px;
    font-weight: 700;
    color: {TEAL};
    background: {MINT};
    border: 1px solid {MINT_BORDER};
    border-radius: 999px;
    padding: 3px 11px;
}}

/* --- Randonnée --- */
.hike-title {{
    font-family: 'Archivo', system-ui, sans-serif;
    font-weight: 700;
    font-size: 21px;
    line-height: 1.2;
    letter-spacing: -0.3px;
    margin-bottom: 10px;
}}
.tags {{ display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 14px; }}
.tag {{
    display: inline-block;
    font-size: 12.5px;
    font-weight: 600;
    color: {BODY};
    background: #FFFFFF;
    border: 1px solid {MINT_BORDER};
    border-radius: 999px;
    padding: 5px 13px;
}}
.tag--difficulty {{ font-weight: 700; }}
.hike-address {{ font-family: ui-monospace, Menlo, monospace; font-size: 11.5px; color: {MUTED}; margin-bottom: 14px; }}
.hike-description {{ font-size: 14px; line-height: 1.62; color: {BODY}; margin-bottom: 20px; }}
.hike-map {{
    margin-bottom: 20px;
    border: 1px solid {NEUTRAL_BORDER};
    border-radius: 14px;
    background: #FFFFFF;
    break-inside: avoid;
}}
.hike-map__img {{ display: block; width: 100%; border-radius: 14px; }}
.subhead {{
    display: block;
    font-size: 10.5px;
    font-weight: 800;
    letter-spacing: 1.6px;
    text-transform: uppercase;
    color: {TERTIARY};
    margin-bottom: 12px;
}}
.step {{ display: flex; gap: 14px; align-items: flex-start; margin-bottom: 11px; break-inside: avoid; }}
.step:last-child {{ margin-bottom: 0; }}
/* inline-block : comme les pilules/badges plus haut, un <span> à bordure arrondie
   laissé en inline voit WeasyPrint dessiner la bordure deux fois (un anneau
   fantôme à l'intérieur de la pastille). inline-block fixe la boîte et supprime
   ce doublon. */
.step__number {{
    display: inline-block;
    flex: none;
    width: 26px;
    height: 26px;
    border-radius: 50%;
    background: {MINT};
    border: 1px solid {MINT_BORDER_2};
    color: {TEAL};
    font-family: 'Archivo', system-ui, sans-serif;
    font-weight: 800;
    font-size: 12.5px;
    line-height: 24px;
    text-align: center;
    margin-top: 1px;
}}
.step__text {{ font-size: 13px; line-height: 1.6; color: {BODY}; }}
.step__caution {{ color: #9A7A2E; font-weight: 600; }}
.step__note {{ color: {MUTED}; }}

/* --- Spot --- */
.spot-card {{
    margin-top: 24px;
    background: #FFFFFF;
    border: 1px solid {NEUTRAL_BORDER};
    border-radius: 14px;
    padding: 20px 22px;
    break-inside: avoid;
}}
.spot-rating {{
    display: inline-block;
    font-size: 12px;
    font-weight: 700;
    color: {INK};
    background: #F1F7E0;
    border: 1px solid #D5E5A8;
    border-radius: 999px;
    padding: 3px 11px;
}}
.spot-rating__star {{ color: {STAR}; }}
.spot-name {{ font-family: 'Archivo', system-ui, sans-serif; font-weight: 700; font-size: 17px; margin-bottom: 3px; }}
.spot-address {{ font-family: ui-monospace, Menlo, monospace; font-size: 11.5px; color: {MUTED}; margin-bottom: 11px; }}
.spot-description {{ font-size: 13.5px; line-height: 1.58; color: {BODY}; margin-bottom: 12px; }}
.spot-link {{ font-size: 12.5px; font-weight: 600; color: {TEAL}; }}

/* --- Services --- */
.services {{ margin-top: 18px; break-inside: avoid; }}
.services__list {{
    border: 1px solid {NEUTRAL_BORDER};
    border-radius: 14px;
    background: #FFFFFF;
}}
.service {{
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 13px 18px;
    border-bottom: 1px solid {SEPARATOR};
}}
.service:last-child {{ border-bottom: 0; }}
.service__dot {{ display: block; flex: none; width: 11px; height: 11px; border-radius: 50%; }}
.service__name {{ font-size: 14px; font-weight: 700; color: {INK}; }}
.service__address {{ font-size: 12.5px; color: {MUTED}; }}
.service__category {{ font-size: 12px; color: {TERTIARY}; margin-left: auto; padding-left: 12px; }}

/* --- Vide (journée sans rando / sans spot / sans service) --- */
.empty {{
    font-size: 13.5px;
    color: {MUTED};
    background: #FFFFFF;
    border: 1px dashed {NEUTRAL_BORDER};
    border-radius: 14px;
    padding: 16px 18px;
}}

/* --- Clôture --- */
.vany-note {{
    margin-top: 30px;
    display: flex;
    align-items: center;
    gap: 20px;
    background: {MINT};
    border: 1px solid {MINT_BORDER};
    border-radius: 16px;
    padding: 20px 26px;
    break-inside: avoid;
}}
.vany-note__img {{ flex: none; width: 96px; }}
.vany-note__eyebrow {{
    display: block;
    font-size: 10.5px;
    font-weight: 800;
    letter-spacing: 2px;
    text-transform: uppercase;
    color: {TEAL};
    margin-bottom: 5px;
}}
.vany-note__title {{
    font-family: 'Archivo', system-ui, sans-serif;
    font-weight: 700;
    font-size: 19px;
    letter-spacing: -0.3px;
    margin-bottom: 5px;
}}
.vany-note__text {{ font-size: 13.5px; line-height: 1.55; color: {BODY}; }}
.footer {{
    margin-top: 18px;
    text-align: center;
    font-family: ui-monospace, Menlo, monospace;
    font-size: 10.5px;
    color: {FOOTER_GREY};
    letter-spacing: 0.3px;
}}
"""


# ---------------------------------------------------------------------------
# Fragments de gabarit
# ---------------------------------------------------------------------------

def _lockup_html() -> str:
    """Lockup « RandoVanGo » : « Rando » encre + « VanGo » teal, chapeau de Vany
    posé sur le « n » (assemblage HTML/CSS, comme sur le site)."""
    hat = _asset_data_uri("logo", "hat.png")
    return (
        f'<span class="lockup">Rando<span class="lockup__teal">Va</span>'
        f'<span class="lockup__n">n<img class="lockup__hat" src="{hat}" alt=""></span>'
        f'<span class="lockup__teal">Go</span></span>'
    )


def _difficulty_tag(difficulte) -> str:
    if not difficulte:
        return ""
    background, border, color = DIFFICULTY_BADGES.get(
        difficulte.strip().lower(), (MINT, MINT_BORDER, TEAL))
    return (f'<span class="tag tag--difficulty" style="background:{background};'
            f'border-color:{border};color:{color};">{escape(difficulte)}</span>')


_STEP_NAME_RE = re.compile(r"^\s*étape\s*\d+\s*$", re.IGNORECASE)
# Mentions entre crochets des descriptifs d'étape : les avertissements
# ([prudence !], [danger]…) sont mis en avant, les autres notes restent discrètes.
_BRACKET_RE = re.compile(r"\[[^\]]*\]")
_CAUTION_RE = re.compile(r"prudence|danger|attention", re.IGNORECASE)


def _highlight_brackets(text: str) -> str:
    """Colore les mentions entre crochets d'un descriptif d'étape (le texte doit
    déjà être échappé : on n'ajoute que des balises de style)."""
    def replace(match):
        content = match.group(0)
        css_class = "step__caution" if _CAUTION_RE.search(content) else "step__note"
        return f'<span class="{css_class}">{content}</span>'
    return _BRACKET_RE.sub(replace, text)


def _step_item(index, waypoint) -> str:
    # Le numéro (pastille) suffit déjà à repérer l'étape : un nom du type "Étape N"
    # (issu tel quel du GPX) est redondant et n'est donc pas ré-affiché à côté.
    raw_name = (waypoint.get("name") or "").strip()
    name = "" if _STEP_NAME_RE.match(raw_name) else escape(raw_name)
    desc_html = _highlight_brackets(escape(waypoint.get("desc") or ""))
    if name and desc_html:
        text = f"<strong>{name}</strong> - {desc_html}"
    else:
        text = f"<strong>{name}</strong>" if name else (desc_html or f"Étape {index}")
    return (f'<div class="step"><span class="step__number">{index}</span>'
            f'<p class="step__text">{text}</p></div>')


def _hike_map_html(day) -> str:
    """Carte dédiée à la rando : tracé zoomé + étapes du GPX numérotées, dont les
    numéros renvoient à la liste « Itinéraire pas à pas » juste en dessous."""
    png_bytes = render_hike_map_png(day.get("hike_mongo_id"), *HIKE_MAP_PX)
    if not png_bytes:
        return ""
    return (f'<div class="hike-map"><img class="hike-map__img" '
            f'src="{_data_uri(png_bytes)}" alt="Carte de la randonnée"></div>')


def _hike_section(day) -> str:
    if not day.get("hike_id"):
        return ('<div class="section-head"><span class="eyebrow">Randonnée du jour</span>'
                '<span class="section-head__rule"></span></div>'
                '<p class="empty">Pas de randonnée aujourd\'hui - journée détente.</p>')

    verified = ('<span class="verified-badge">✓ Vérifiée</span>'
                if day.get("hike_verifie") else "")

    tags = []
    if day.get("distance_km") is not None:
        tags.append(f'<span class="tag">{_fr_measure(day["distance_km"])} km</span>')
    if day.get("hike_duration_h") is not None:
        tags.append(f'<span class="tag">{_fr_measure(day["hike_duration_h"])} h de marche</span>')
    if day.get("elevation_gain_m") is not None:
        tags.append(f'<span class="tag">{_fr_int(day["elevation_gain_m"])} m D+</span>')
    tags.append(_difficulty_tag(day.get("difficulte")))

    # Adresse du point de départ (géocodée à l'import, cf. etl/backfill_addresses.py) :
    # affichée quand elle est connue - un départ isolé (parking de sentier) n'en a pas.
    address_html = (f'<div class="hike-address">Départ&nbsp;: {escape(day["hike_address"])}</div>'
                    if day.get("hike_address") else "")

    description = escape((day.get("hike_description") or "").strip())
    description_html = f'<p class="hike-description">{description}</p>' if description else ""

    waypoints = fetch_hike_waypoints(day.get("hike_mongo_id"))
    steps_html = ""
    if waypoints:
        steps = "".join(_step_item(i, wp) for i, wp in enumerate(waypoints, start=1))
        steps_html = f'<span class="subhead">Itinéraire pas à pas</span><div>{steps}</div>'

    return f"""
    <div class="section-head">
        <span class="eyebrow">Randonnée du jour</span>
        <span class="section-head__rule"></span>
        {verified}
    </div>
    <div class="hike-title">{escape(day.get("hike_name") or "")}</div>
    <div class="tags">{"".join(tags)}</div>
    {address_html}
    {description_html}
    {_hike_map_html(day)}
    {steps_html}
    """


def _spot_section(day) -> str:
    if not day.get("spot_id"):
        return ('<div class="services"><div class="section-head">'
                '<span class="eyebrow">Spot pour la nuit</span>'
                '<span class="section-head__rule section-head__rule--soft"></span></div>'
                '<p class="empty">Aucun spot sélectionné pour cette nuit.</p></div>')

    rating = day.get("spot_rating")
    rating_html = (f'<span class="spot-rating"><span class="spot-rating__star">★</span> '
                   f'{_fr_number(rating, 1)} / 5</span>') if rating else ""
    address = (f'<div class="spot-address">{escape(day["spot_address"])}</div>'
               if day.get("spot_address") else "")
    description = escape((day.get("spot_description") or "").strip())
    description_html = f'<p class="spot-description">{description}</p>' if description else ""
    link = (f'<a class="spot-link" href="{escape(day["spot_url"])}">Voir sur park4night&nbsp;↗</a>'
            if day.get("spot_url") else "")
    # Le type ("Parking jour et nuit") complète le nom, souvent une simple adresse.
    spot_type = f' - {escape(day["spot_type"].capitalize())}' if day.get("spot_type") else ""

    return f"""
    <div class="spot-card">
        <div class="section-head">
            <span class="eyebrow">Spot pour la nuit</span>
            <span class="section-head__rule section-head__rule--soft"></span>
            {rating_html}
        </div>
        <div class="spot-name">{escape(day.get("spot_name") or "")}{spot_type}</div>
        {address}
        {description_html}
        {link}
    </div>
    """


def _services_section(day) -> str:
    pois = day.get("pois") or []
    if not pois:
        return ('<div class="services"><span class="eyebrow">Services de la journée</span>'
                '<p class="empty" style="margin-top:12px;">Aucun service renseigné pour cette journée.</p></div>')

    def _service_item(poi):
        color, _, category_label = POI_CATEGORY_STYLES.get(poi.get("category"), DEFAULT_POI_STYLE)
        name = (poi.get("name") or "").strip()
        address = (f'<span class="service__address">· {escape(poi["address"])}</span>'
                   if poi.get("address") else "")
        # Le type de service ("Restaurant") nomme la colonne de droite ; s'il ne
        # fait que répéter le nom du lieu, on retombe sur le libellé de catégorie.
        raw_type = (poi.get("service_type") or "").strip()
        category = raw_type if raw_type and raw_type.lower() != name.lower() else category_label
        return (f'<div class="service"><span class="service__dot" style="background:{color};"></span>'
                f'<span class="service__name">{escape(name)}</span>{address}'
                f'<span class="service__category">{escape(category)}</span></div>')

    items = "".join(_service_item(poi) for poi in pois)
    return f"""
    <div class="services">
        <span class="eyebrow">Services de la journée</span>
        <div class="services__list" style="margin-top:12px;">{items}</div>
    </div>
    """


# ---------------------------------------------------------------------------
# Couverture
# ---------------------------------------------------------------------------

def _trip_totals(days) -> dict:
    """Totaux affichés en puces de couverture (sommes sur les jours planifiés)."""
    return {
        "days": len(days),
        "distance_km": sum(d.get("distance_km") or 0 for d in days),
        "elevation_m": sum(d.get("elevation_gain_m") or 0 for d in days),
        "nights": sum(1 for d in days if d.get("spot_id")),
        "hikes": sum(1 for d in days if d.get("hike_id")),
    }


def _cover_subtitle(plan, totals) -> str:
    """Sous-titre de couverture : situe le séjour (lieu, durée) et annonce ce que
    contient le carnet."""
    # « autour de Telgruc-sur-Mer - Finistère, Bretagne » : le département et la
    # région sont apposés après un tiret, aucune préposition ne convenant à tous
    # les noms ("dans le Finistère", "en Bretagne", "à Paris"…).
    city = plan.get("city_name")
    area = ", ".join(p for p in (plan.get("city_department"), plan.get("city_region")) if p)
    place = " - ".join(p for p in (city, area) if p)
    location = f" autour de {escape(place)}" if place else ""
    contents = [_plural(totals["hikes"], "randonnée")] if totals["hikes"] else []
    if totals["nights"]:
        contents.append(_plural(totals["nights"], "spot") + " pour la nuit")
    contents_text = ", ".join(contents)
    sentence = (f"{contents_text.capitalize()} et les services utiles à proximité."
                if contents_text else "Ton itinéraire jour par jour.")
    return f"{_plural(totals['days'], 'jour')} en van{location}. {sentence}"


def _cover_pills(totals) -> str:
    pills = [_plural(totals["days"], "jour")]
    if totals["distance_km"]:
        pills.append(f'{_fr_measure(totals["distance_km"])} km à pied')
    if totals["elevation_m"]:
        pills.append(f'{_fr_int(totals["elevation_m"])} m de dénivelé')
    if totals["nights"]:
        pills.append(_plural(totals["nights"], "nuit") + " en spot")
    return "".join(f'<span class="pill">{escape(p)}</span>' for p in pills)


def _map_section(days) -> str:
    """Carte de l'itinéraire : le vrai rendu (tracés GPX + marqueurs), avec la
    légende des seules catégories présentes dans ce séjour."""
    png_bytes = render_overview_map_png(days, *OVERVIEW_MAP_PX)
    if not png_bytes:
        return ""

    items = []
    for entry in legend_entries(days):
        if entry["shape"] == "bar":
            mark = '<span class="legend-bar"></span>'
        else:
            mark = f'<img class="legend-pin" src="{_data_uri(entry["icon_png"])}" alt="">'
        items.append(f'<span class="legend-item">{mark}{escape(entry["label"])}</span>')

    return f"""
    <div class="map-card">
        <img class="map-card__img" src="{_data_uri(png_bytes)}" alt="Carte de l'itinéraire">
        <div class="map-legend">{"".join(items)}</div>
    </div>
    """


def _cover_section(plan, days, totals) -> str:
    return f"""
    <div class="cover-head">
        {_lockup_html()}
        <span class="cover-head__date">Établi le {_long_date(date.today(), weekday=False)}</span>
    </div>
    <div class="rule"></div>
    <div class="hero">
        <div class="hero__text">
            <span class="hero__eyebrow">Carnet de voyage</span>
            <div class="hero__title">{escape(plan.get("city_name") or "Ton séjour")}</div>
            <div class="hero__subtitle">{_cover_subtitle(plan, totals)}</div>
        </div>
        <img class="hero__vany" src="{_asset_data_uri("vany", "front.png")}"
             alt="Vany, la mascotte van de RandoVanGo">
    </div>
    <div class="pills">{_cover_pills(totals)}</div>
    {_map_section(days)}
    """


# ---------------------------------------------------------------------------
# Clôture : le mot de Vany
# ---------------------------------------------------------------------------

# Un séjour "en bord de mer" ne se déduit d'aucune colonne : on le repère aux
# mots des noms/descriptions des randos et des spots retenus.
_SEASIDE_RE = re.compile(r"\bmer\b|plage|côt|littoral|dune|falaise|océan|baie|anse|port",
                         re.IGNORECASE)
BIG_CLIMB_M = 500


def _is_seaside(days) -> bool:
    for day in days:
        haystack = " ".join(str(day.get(field) or "") for field in
                            ("hike_name", "hike_description", "spot_name",
                             "spot_address", "spot_description"))
        if _SEASIDE_RE.search(haystack):
            return True
    return False


def vany_note(plan, days, totals) -> dict:
    """Mot de clôture de Vany : titre + conseil, choisis d'après le séjour
    (bord de mer, dénivelé, randonnée difficile). Fonction pure, testée dans
    tests/services/test_pdf_service.py."""
    city = plan.get("city_name") or "la région"
    tips = []
    if _is_seaside(days):
        tips.append("Pense à vérifier les horaires de marée avant de partir longer la côte")
    if totals["elevation_m"] >= BIG_CLIMB_M:
        tips.append(f'garde de l\'eau pour les {_fr_int(totals["elevation_m"])} m de montée')
    if any((d.get("difficulte") or "").strip().lower() == "difficile" for d in days):
        tips.append("pars de bonne heure les jours de grosse randonnée")
    if not tips:
        tips.append("Prends le temps de flâner, le meilleur du voyage est souvent en chemin")

    # Conseils enchaînés en une seule phrase : "A, B et C".
    advice = tips[0] if len(tips) == 1 else ", ".join(tips[:-1]) + " et " + tips[-1]
    return {
        "title": f"Bonne route autour de {city} !",
        "text": f"{advice}. On se retrouve sur RandoVanGo pour le prochain voyage.",
    }


def _closing_section(plan, days, totals) -> str:
    note = vany_note(plan, days, totals)
    city = escape(plan.get("city_name") or "")
    footer = f'RandoVanGo · carnet de voyage · {city} · {_plural(totals["days"], "jour")} · randovango.fr'
    return f"""
    <div class="vany-note">
        <img class="vany-note__img" src="{_asset_data_uri("vany", "waiting.png")}"
             alt="Vany te souhaite bonne route">
        <div>
            <span class="vany-note__eyebrow">Le mot de Vany</span>
            <div class="vany-note__title">{escape(note["title"])}</div>
            <p class="vany-note__text">{escape(note["text"])}</p>
        </div>
    </div>
    <div class="footer">{footer}</div>
    """


# ---------------------------------------------------------------------------
# Document
# ---------------------------------------------------------------------------

def _day_section(day, start_date) -> str:
    date_label = _day_date_label(start_date, day["day_number"])
    return f"""
    <div class="day">
        <div class="day-header">
            <div class="day-header__left">
                <span class="day-badge">Jour {day["day_number"]}</span>
                <span class="day-city">{escape(day.get("city_name") or "")}</span>
            </div>
            <span class="day-date">{escape(date_label)}</span>
        </div>
        {_hike_section(day)}
        {_spot_section(day)}
        {_services_section(day)}
    </div>
    """


def render_trip_pdf_html(plan: dict) -> str:
    days = plan.get("days", [])
    totals = _trip_totals(days)
    city_name = escape(plan.get("city_name") or "")

    if days:
        body = ("".join(_day_section(day, plan.get("start_date")) for day in days)
                + _closing_section(plan, days, totals))
    else:
        body = '<p class="empty">Aucun jour planifié pour ce voyage.</p>'

    return f"""
    <!doctype html>
    <html lang="fr">
    <head>
        <meta charset="utf-8">
        <title>Carnet de voyage - {city_name}</title>
        <style>{CSS}</style>
    </head>
    <body>
        {_cover_section(plan, days, totals)}
        {body}
    </body>
    </html>
    """
