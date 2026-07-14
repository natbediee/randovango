"""
Préparation des textes prêts à afficher pour le frontend.

Toute la logique de présentation (libellés français, pluriels, badges,
catégories, formatage des nombres et des dates) vit ICI, en Python.
Le JavaScript ne fait plus que recevoir ces champs et les insérer dans la page.

Conventions de nommage des champs ajoutés aux réponses API :
  - *_label : texte prêt à afficher ("350 m", "⭐ 4.2/5", "Lundi 7 juil")
  - *_css   : nom de classe CSS à appliquer ("good-weather", "facile")
  - badge   : dictionnaire {"text": "Vérifié", "css": "verified"}

Les fonctions sont pures (pas d'accès base de données) : elles sont testées
dans tests/utils/test_display_utils.py.
"""

import math
from datetime import date, datetime

# ---------------------------------------------------------------------------
# Petits utilitaires de formatage "à la JavaScript"
# ---------------------------------------------------------------------------
# Le frontend historique insérait les nombres bruts dans les textes : en JS,
# 13.0 s'affiche "13" et 13.5 s'affiche "13.5". On reproduit ce comportement
# pour que les textes générés en Python soient identiques à l'ancien affichage.


def js_num(value) -> str:
    """Formate un nombre comme le ferait JavaScript (13.0 → "13", 13.5 → "13.5")."""
    if value is None:
        return ""
    return f"{float(value):g}"


def js_round(value) -> int:
    """Arrondi à la JavaScript : Math.round arrondit toujours 0.5 vers le haut,
    alors que le round() de Python arrondit 0.5 vers le pair le plus proche."""
    return math.floor(float(value) + 0.5)


def verified_badge(verifie) -> dict:
    """Badge de vérification affiché sur les cartes randonnée/spot/service."""
    if verifie:
        return {"text": "Vérifié", "css": "verified"}
    return {"text": "En attente", "css": "pending"}


# ---------------------------------------------------------------------------
# Météo (étape 1)
# ---------------------------------------------------------------------------

# Jours et mois en français pour les entêtes des cartes météo.
FR_WEEKDAYS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
FR_MONTHS_SHORT = ["janv", "févr", "mars", "avr", "mai", "juin",
                   "juil", "août", "sept", "oct", "nov", "déc"]

# Conseil de randonnée associé à chaque pictogramme météo
# (icône Font Awesome + phrase affichée sous la carte météo).
WEATHER_ADVICE = {
    "sun":           {"icon": "fa-check-circle",         "text": "Parfait pour randonner"},
    "partly_cloudy": {"icon": "fa-check-circle",         "text": "Parfait pour randonner"},
    "storm":         {"icon": "fa-exclamation-triangle", "text": "Éviter les randos"},
    "rain":          {"icon": "fa-info-circle",          "text": "Équipements conseillés"},
    "snow":          {"icon": "fa-info-circle",          "text": "Équipements conseillés"},
    "fog":           {"icon": "fa-eye-slash",            "text": "Avec prudence"},
    "cloud":         {"icon": "fa-cloud",                "text": "Conditions correctes"},
    "indisponible":  {"icon": "fa-question-circle",      "text": "Météo indisponible"},
}

# Par beau temps, on remplace le conseil par un avertissement chaleur
# dès que la température maximale atteint ce seuil.
HEAT_ADVICE_THRESHOLD_C = 25
GOOD_WEATHER_PICTOS = ("sun", "partly_cloudy", "cloud")


def weather_css(weather_code) -> str:
    """Classe CSS de la carte météo selon le code météo Open-Meteo :
    beau temps (fond vert), acceptable (orange), mauvais (rouge)."""
    if weather_code is None:
        return "good-weather"
    if 45 <= weather_code <= 65:
        return "acceptable-weather"
    if weather_code > 65:
        return "bad-weather"
    return "good-weather"


def weather_advice(picto, temp_max) -> dict:
    """Conseil de randonnée du jour : celui du pictogramme, sauf par beau temps
    chaud où l'on conseille plutôt de partir tôt."""
    if picto in GOOD_WEATHER_PICTOS and temp_max is not None \
            and temp_max >= HEAT_ADVICE_THRESHOLD_C:
        return {"icon": "fa-sun", "text": "Partez de bonne heure"}
    return WEATHER_ADVICE.get(picto, WEATHER_ADVICE["indisponible"])


def meteo_day_label(forecast_date, index) -> str:
    """Entête de la carte météo : "Aujourd'hui" pour la première prévision,
    sinon "Lundi 7 juil". (La première prévision est toujours celle du jour :
    on se fie à sa position, pas à la date système.)"""
    if index == 0:
        return "Aujourd'hui"
    if isinstance(forecast_date, str):
        forecast_date = datetime.strptime(forecast_date, "%Y-%m-%d").date()
    return (f"{FR_WEEKDAYS[forecast_date.weekday()]} "
            f"{forecast_date.day} {FR_MONTHS_SHORT[forecast_date.month - 1]}")


def enrich_meteo_forecasts(forecasts) -> list:
    """Ajoute à chaque prévision météo ses champs prêts à afficher :
    day_label, css, advice, températures/pluie/vent formatés."""
    for index, f in enumerate(forecasts):
        f["day_label"] = meteo_day_label(f.get("date"), index)
        f["css"] = weather_css(f.get("weather_code"))
        f["advice"] = weather_advice(f.get("picto"), f.get("temp_max"))
        f["temp_max_label"] = f"{js_round(f['temp_max'])}°" if f.get("temp_max") is not None else "?"
        f["temp_min_label"] = f"{js_round(f['temp_min'])}°" if f.get("temp_min") is not None else "?"
        # Pluie et vent : affichés seulement s'ils sont non nuls (None sinon).
        precipitation = f.get("precipitation_sum") or 0
        f["precipitation_label"] = f"{float(precipitation):.1f} mm" if precipitation > 0 else None
        wind = f.get("wind_speed_max") or 0
        f["wind_label"] = f"{js_round(wind)} km/h" if wind > 0 else None
    return forecasts


def city_stats_labels(stats) -> dict:
    """Libellés de la fiche ville : "12 randonnées", "50 spots nuit", ..."""
    return {
        "hikes": f"{stats.get('hikes', 0)} randonnées",
        "spots": f"{stats.get('spots', 0)} spots nuit",
        "poi": f"{stats.get('poi', 0)} points d'intérêt",
    }


# ---------------------------------------------------------------------------
# Randonnées (étape 2)
# ---------------------------------------------------------------------------

def duration_category(duration_h) -> str:
    """Catégorie de durée utilisée par le filtre "Durée" de l'étape 2."""
    if duration_h is None:
        return "long"
    if duration_h < 2:
        return "court"
    if duration_h <= 4:
        return "moyen"
    return "long"


def hike_trace_color(index, total) -> str:
    """Teinte de teal propre à chaque randonnée (dégradé clair → foncé), assortie
    à l'identité Vany, pour distinguer les tracés GPX qui se chevauchent sur la
    carte. Stable car les randonnées sont triées par nom dans la requête SQL."""
    lightness = 50 - (index / (total - 1)) * 20 if total > 1 else 40
    return f"hsl(187, 55%, {js_num(lightness)}%)"


def enrich_hike(hike, index, total) -> dict:
    """Ajoute à une randonnée ses champs prêts à afficher."""
    difficulte = hike.get("difficulte")
    hike["difficulty_css"] = difficulte.lower() if difficulte else "facile"
    hike["difficulty_label"] = difficulte or "N/A"
    hike["duration_category"] = duration_category(hike.get("duration"))
    hike["badge"] = verified_badge(hike.get("verifie"))
    hike["description_label"] = hike.get("description") or "Randonnée sans description"
    # Résumé affiché dans les popups de la carte ("13 km - 4h").
    hike["summary_label"] = f"{js_num(hike.get('distance_km'))} km - {js_num(hike.get('duration'))}h"
    hike["color"] = hike_trace_color(index, total)
    return hike


# ---------------------------------------------------------------------------
# Spots nuit (étape 3)
# ---------------------------------------------------------------------------

# Types de spots (colonne spots.type) classés gratuit/payant pour le filtre
# "Prix" de l'étape 3. Tout type absent de ces listes est classé "autres".
SPOT_TYPES_GRATUIT = (
    "AIRE CC STAT. GRATUIT",
    "PARKING CC SANS SERVICES",
    "PARKING JOUR ET NUIT",
    "AIRE DE REPOS",
)
SPOT_TYPES_PAYANT = (
    "AIRE CC STAT. PAYANT",
    "CAMPING",
    "AIRE CC PRIVÉE",
    "ACCUEIL ENTRE PARTICULIERS",
    "A LA FERME (FERME, VIGNOBLE ...)",
)

# Icône affichée devant chaque service d'un spot (recherche par inclusion,
# insensible à la casse : "eau potable" → 💧). "✓" par défaut.
SPOT_SERVICE_ICONS = {
    "Eau": "💧",
    "WC": "🚽",
    "Douche": "🚿",
    "Électricité": "⚡",
    "WiFi": "📶",
    "Restaurant": "🍽️",
    "Supermarché": "🛒",
    "Boulangerie": "🥐",
    "Parking": "🅿️",
    "Plage": "🏖️",
    "Vue mer": "🌅",
}


def spot_category(spot_type) -> str:
    """Catégorie prix d'un spot : "gratuit", "payant" ou "autres"."""
    if not spot_type:
        return "autres"
    t = spot_type.upper().strip()
    if t in SPOT_TYPES_GRATUIT:
        return "gratuit"
    if t in SPOT_TYPES_PAYANT:
        return "payant"
    return "autres"


def spot_service_display(service_name) -> dict:
    """Icône + nom d'un service de spot, prêt à afficher."""
    lower = service_name.lower()
    for key, icon in SPOT_SERVICE_ICONS.items():
        if key.lower() in lower:
            return {"icon": icon, "name": service_name}
    return {"icon": "✓", "name": service_name}


def enrich_spot(spot) -> dict:
    """Ajoute à un spot ses champs prêts à afficher."""
    spot["category"] = spot_category(spot.get("type"))
    spot["type_label"] = spot.get("type") or "Bivouac"
    spot["badge"] = verified_badge(spot.get("verifie"))
    spot["description_label"] = spot.get("description") or "Aucune description disponible"
    rating = spot.get("rating")
    spot["rating_label"] = f"⭐ {js_num(rating)}/5" if rating else None
    spot["services_display"] = [spot_service_display(s) for s in spot.get("services", [])]
    return spot


# ---------------------------------------------------------------------------
# Services / POI (étape 4)
# ---------------------------------------------------------------------------

# Libellés français de chaque catégorie de services, avec le genre pour
# accorder la phrase "Aucun/Aucune ... disponible".
POI_CATEGORY_LABELS = {
    "tout":         {"singular": "service",             "plural": "services",             "gender": "m"},
    "eau":          {"singular": "point d'eau",         "plural": "points d'eau",         "gender": "m"},
    "vidange":      {"singular": "station de vidange",  "plural": "stations de vidange",  "gender": "f"},
    "gasoil":       {"singular": "point carburant",     "plural": "points carburant",     "gender": "m"},
    "supermarche":  {"singular": "supermarché",         "plural": "supermarchés",         "gender": "m"},
    "commerce":     {"singular": "commerce",            "plural": "commerces",            "gender": "m"},
    "restauration": {"singular": "restaurant",          "plural": "restaurants",          "gender": "m"},
    "toilettes":    {"singular": "point toilettes",     "plural": "points toilettes",     "gender": "m"},
    "hygiene":      {"singular": "point hygiène",       "plural": "points hygiène",       "gender": "m"},
    "culture":      {"singular": "site culturel",       "plural": "sites culturels",      "gender": "m"},
    "urgence":      {"singular": "service d'urgence",   "plural": "services d'urgence",   "gender": "m"},
}


def distance_label(distance_km) -> str:
    """Distance lisible : "350 m" en dessous d'un kilomètre, sinon "1.2 km"."""
    if distance_km is None:
        return ""
    if distance_km < 1:
        return f"{js_round(distance_km * 1000)} m"
    return f"{js_num(distance_km)} km"


def enrich_poi(poi) -> dict:
    """Ajoute à un POI (service) ses champs prêts à afficher."""
    poi["service_type_label"] = poi.get("service_type") or "Service"
    poi["distance_label"] = distance_label(poi.get("distance_km"))
    poi["badge"] = verified_badge(poi.get("verifie"))
    return poi


def poi_subtitle(category, count) -> str:
    """Phrase "X services disponibles pour cette journée" de l'étape 4,
    accordée en genre et en nombre selon la catégorie."""
    labels = POI_CATEGORY_LABELS.get(category, POI_CATEGORY_LABELS["tout"])
    if count == 0:
        aucun = "Aucune" if labels["gender"] == "f" else "Aucun"
        return f"{aucun} {labels['singular']} disponible pour cette journée"
    noun = labels["plural"] if count > 1 else labels["singular"]
    s = "s" if count > 1 else ""
    return f"{count} {noun} disponible{s} pour cette journée"


# ---------------------------------------------------------------------------
# Récapitulatif (page results)
# ---------------------------------------------------------------------------

def result_day_display(day) -> dict:
    """Contenu prêt à afficher des cellules du tableau récapitulatif.

    Les champs *_html peuvent contenir du HTML simple (<br>, <small>) inséré
    tel quel par le JS (innerHTML) — même comportement que l'ancien affichage,
    les données venant de nos propres bases.
    """
    if day.get("hike_id"):
        distance = js_num(day["distance_km"]) if day.get("distance_km") is not None else "?"
        activity = f"{day.get('hike_name')} ({distance} km, {day.get('difficulte') or ''})"
    else:
        activity = "Pas de randonnée - Détente"

    if day.get("spot_id"):
        accommodation = day.get("spot_name") or ""
        if day.get("spot_address"):
            accommodation += f"<br><small>📍 {day['spot_address']}</small>"
    else:
        accommodation = "Aucun spot sélectionné"

    pois = day.get("pois") or []
    if pois:
        services = "<br>".join(
            f"{p.get('name')}" + (f" <small>📍 {p['address']}</small>" if p.get("address") else "")
            for p in pois
        )
    else:
        services = "Aucun service"

    return {
        "day_title": f"Jour {day.get('day_number')}",
        "activity_html": activity,
        "accommodation_html": accommodation,
        "services_html": services,
    }
