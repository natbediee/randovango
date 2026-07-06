"""
Construction du HTML du carnet de voyage, converti en PDF par WeasyPrint
(voir backend/api/routers/result.py, route GET /api/result/pdf).
"""
import base64
import re
from datetime import timedelta
from html import escape

from services.map_service import render_overview_map_png, render_hike_map_png, fetch_hike_waypoints, legend_entries

DIFFICULTY_COLORS = {
    "facile": "#4CAF50",
    "moyen": "#FF9800",
    "difficile": "#F44336",
}

CSS = """
@page {
    size: A4;
    margin: 2cm 1.8cm;
    @bottom-center {
        content: "RandoVanGo — page " counter(page) " / " counter(pages);
        font-size: 9px;
        color: #757575;
    }
}
* { box-sizing: border-box; }
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif;
    color: #2E2E2E;
    font-size: 12px;
    line-height: 1.5;
}
h1 { color: #2E4A6B; font-size: 26px; margin: 0 0 4px 0; }
h2 { color: #4B6F8E; font-size: 18px; margin: 0 0 10px 0; }
h3 { color: #2E4A6B; font-size: 14px; margin: 0 0 6px 0; }
.cover {
    text-align: center;
    margin-bottom: 24px;
    padding-bottom: 16px;
    border-bottom: 3px solid #4B6F8E;
}
.cover .subtitle { color: #757575; font-size: 13px; }
.day {
    page-break-inside: avoid;
    margin-bottom: 22px;
    border: 1px solid #E0E0E0;
    border-radius: 8px;
    padding: 14px 16px;
}
.day-header {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    border-bottom: 2px solid #F5F5F5;
    padding-bottom: 6px;
    margin-bottom: 10px;
}
.day-header .day-date { color: #757575; font-size: 12px; }
.block {
    margin-bottom: 10px;
    padding-left: 10px;
    border-left: 4px solid #E0E0E0;
}
.block-hike { border-left-color: #4B6F8E; }
.block-spot { border-left-color: #26C6A6; }
.block-poi { border-left-color: #9E9E9E; }
.block-title {
    font-weight: 600;
    color: #2E4A6B;
    margin-bottom: 3px;
}
.badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 10px;
    font-size: 10px;
    font-weight: 600;
    color: #fff;
    margin-left: 6px;
}
.stats { color: #4B6F8E; font-size: 11px; margin-bottom: 4px; }
.description { color: #444; white-space: pre-line; }
.poi-list { margin: 4px 0 0 0; padding-left: 18px; }
.poi-list li { margin-bottom: 2px; }
.empty { color: #999; font-style: italic; }
small.address { color: #757575; }
.map-section {
    margin-bottom: 24px;
    text-align: center;
}
.map-section img {
    width: 100%;
    max-width: 100%;
    border-radius: 8px;
    border: 1px solid #E0E0E0;
}
.legend {
    display: flex;
    flex-wrap: wrap;
    justify-content: center;
    gap: 16px 32px;
    margin-top: 10px;
    font-size: 10px;
    color: #444;
}
.legend-item { display: flex; align-items: center; gap: 6px; }
.legend-icon {
    display: inline-block;
    width: 16px;
    height: 16px;
}
.hike-map {
    margin: 6px 0 10px 0;
    padding-left: 10px;
    border-left: 4px solid #4B6F8E;
    page-break-inside: avoid;
}
.hike-map img {
    width: 100%;
    max-width: 100%;
    border-radius: 8px;
    border: 1px solid #E0E0E0;
    margin-bottom: 8px;
}
.step-list {
    list-style: none;
    margin: 0;
    padding: 0;
    font-size: 10px;
    color: #444;
}
.step-list li {
    display: flex;
    align-items: flex-start;
    gap: 8px;
    margin-bottom: 4px;
}
.step-number {
    flex-shrink: 0;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 16px;
    height: 16px;
    border-radius: 50%;
    background: #4B6F8E;
    color: #fff;
    font-size: 9px;
    font-weight: 700;
}
.step-text { line-height: 1.4; }
"""


def _difficulty_badge(difficulte):
    if not difficulte:
        return ""
    color = DIFFICULTY_COLORS.get(difficulte.lower(), "#757575")
    return f'<span class="badge" style="background:{color}">{escape(difficulte)}</span>'


_STEP_NAME_RE = re.compile(r"^\s*étape\s*\d+\s*$", re.IGNORECASE)


def _step_item(index, waypoint):
    # Le numéro (badge rond) suffit déjà à repérer l'étape : un nom du type "Étape N"
    # (issu tel quel du GPX) est redondant et n'est donc pas ré-affiché à côté.
    raw_name = (waypoint.get("name") or "").strip()
    name = "" if _STEP_NAME_RE.match(raw_name) else escape(raw_name)
    desc = waypoint.get("desc")
    desc_html = escape(desc) if desc else ""
    if name and desc_html:
        text = f"<strong>{name}</strong> — {desc_html}"
    elif name:
        text = f"<strong>{name}</strong>"
    else:
        text = desc_html or f"Étape {index}"
    return f'<li><span class="step-number">{index}</span><span class="step-text">{text}</span></li>'


def _hike_map_section(day):
    """Carte dédiée à la rando (dissociée de la carte générale du jour) : tracé
    zoomé + étapes du GPX numérotées, avec la liste des indications en dessous."""
    if not day.get("hike_id"):
        return ""
    mongo_id = day.get("hike_mongo_id")
    png_bytes = render_hike_map_png(mongo_id)
    if not png_bytes:
        return ""
    b64 = base64.b64encode(png_bytes).decode("ascii")

    waypoints = fetch_hike_waypoints(mongo_id)
    steps_html = ""
    if waypoints:
        items = "".join(_step_item(i, wp) for i, wp in enumerate(waypoints, start=1))
        steps_html = f'<ol class="step-list">{items}</ol>'

    return f"""
    <div class="hike-map">
        <img src="data:image/png;base64,{b64}" alt="Carte de la randonnée">
        {steps_html}
    </div>
    """


def _hike_block(day):
    if not day.get("hike_id"):
        return '<div class="block block-hike"><div class="block-title">Randonnée</div><div class="empty">Pas de randonnée - journée détente</div></div>'

    stats = []
    if day.get("distance_km") is not None:
        stats.append(f'{day["distance_km"]} km')
    if day.get("hike_duration_h") is not None:
        stats.append(f'{day["hike_duration_h"]} h')
    if day.get("elevation_gain_m") is not None:
        stats.append(f'{day["elevation_gain_m"]} m D+')
    stats_html = " · ".join(stats)

    description = escape(day.get("hike_description") or "").strip()
    description_html = f'<div class="description">{description}</div>' if description else ""

    return f"""
    <div class="block block-hike">
        <div class="block-title">Randonnée : {escape(day.get("hike_name") or "")}{_difficulty_badge(day.get("difficulte"))}</div>
        <div class="stats">{stats_html}</div>
        {description_html}
    </div>
    """


def _spot_block(day):
    if not day.get("spot_id"):
        return '<div class="block block-spot"><div class="block-title">Spot</div><div class="empty">Aucun spot sélectionné</div></div>'

    address = f'<br><small class="address">Adresse : {escape(day["spot_address"])}</small>' if day.get("spot_address") else ""
    rating = f' — Note : {day["spot_rating"]}/5' if day.get("spot_rating") else ""
    type_ = f' ({escape(day["spot_type"])})' if day.get("spot_type") else ""
    description = escape(day.get("spot_description") or "").strip()
    description_html = f'<div class="description">{description}</div>' if description else ""
    url = f'<div><small><a href="{escape(day["spot_url"])}">{escape(day["spot_url"])}</a></small></div>' if day.get("spot_url") else ""

    return f"""
    <div class="block block-spot">
        <div class="block-title">Spot : {escape(day["spot_name"])}{type_}{rating}</div>
        {address}
        {description_html}
        {url}
    </div>
    """


def _services_block(day):
    pois = day.get("pois") or []
    if not pois:
        return '<div class="block block-poi"><div class="block-title">Services</div><div class="empty">Aucun service renseigné</div></div>'

    def _poi_item(poi):
        name = poi.get("name") or ""
        raw_type = poi.get("service_type") or ""
        service_type = f' — {escape(raw_type)}' if raw_type and raw_type.strip().lower() != name.strip().lower() else ""
        address = f'<small class="address">Adresse : {escape(poi["address"])}</small>' if poi.get("address") else ""
        return f'<li>{escape(name)}{service_type} {address}</li>'

    items = "".join(_poi_item(poi) for poi in pois)
    return f"""
    <div class="block block-poi">
        <div class="block-title">Services</div>
        <ul class="poi-list">{items}</ul>
    </div>
    """


FR_WEEKDAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
FR_MONTHS = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]


def _day_date_label(start_date, day_number):
    if not start_date:
        return ""
    try:
        date = start_date + timedelta(days=day_number - 1)
    except TypeError:
        return ""
    return f"{FR_WEEKDAYS[date.weekday()]} {date.day:02d} {FR_MONTHS[date.month - 1]} {date.year}"


def _legend_item(icon_bytes, label):
    icon_b64 = base64.b64encode(icon_bytes).decode("ascii")
    return (
        f'<span class="legend-item">'
        f'<img class="legend-icon" src="data:image/png;base64,{icon_b64}" alt="">'
        f'{escape(label)}</span>'
    )


def _global_map_section(days):
    """Carte globale du voyage entier (tous les jours confondus), avec sa légende —
    section à part, en dehors de la boucle des jours (pas dans le bloc "Jour 1")."""
    png_bytes = render_overview_map_png(days)
    if not png_bytes:
        return ""
    b64 = base64.b64encode(png_bytes).decode("ascii")

    legend_html = "".join(_legend_item(icon_bytes, label) for icon_bytes, label in legend_entries(days))
    return f"""
    <div class="map-section">
        <h2>Carte du voyage</h2>
        <img src="data:image/png;base64,{b64}" alt="Carte du voyage">
        <div class="legend">{legend_html}</div>
    </div>
    """


def render_trip_pdf_html(plan: dict) -> str:
    city_name = escape(plan.get("city_name") or "")
    duration_days = plan.get("duration_days")
    start_date = plan.get("start_date")

    days_html = []
    for day in plan.get("days", []):
        date_label = _day_date_label(start_date, day["day_number"])
        day_city = escape(day.get("city_name") or "")
        days_html.append(f"""
        <div class="day">
            <div class="day-header">
                <h2>Jour {day["day_number"]} — {day_city}</h2>
                <span class="day-date">{escape(date_label)}</span>
            </div>
            {_hike_block(day)}
            {_hike_map_section(day)}
            {_spot_block(day)}
            {_services_block(day)}
        </div>
        """)

    return f"""
    <!doctype html>
    <html lang="fr">
    <head>
        <meta charset="utf-8">
        <title>Carnet de voyage - {city_name}</title>
        <style>{CSS}</style>
    </head>
    <body>
        <div class="cover">
            <h1>Carnet de voyage RandoVanGo</h1>
            <div class="subtitle">
                Départ : {city_name}
                {f" · {duration_days} jour(s)" if duration_days else ""}
            </div>
        </div>
        {_global_map_section(plan.get("days", []))}
        {"".join(days_html) if days_html else '<p class="empty">Aucun jour planifié pour ce voyage.</p>'}
    </body>
    </html>
    """
