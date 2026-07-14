"""Tests du module de présentation (fonctions pures, sans base de données)."""

from utils.display_utils import (
    distance_label,
    duration_category,
    enrich_hike,
    enrich_meteo_forecasts,
    enrich_poi,
    enrich_spot,
    hike_trace_color,
    js_num,
    js_round,
    meteo_day_label,
    poi_subtitle,
    result_day_display,
    spot_category,
    verified_badge,
    weather_advice,
    weather_css,
)


# --- Formatage "à la JavaScript" ---

def test_js_num_entier_et_decimal() -> None:
    assert js_num(13.0) == "13"
    assert js_num(13.5) == "13.5"
    assert js_num(None) == ""


def test_js_round_demi_vers_le_haut() -> None:
    # Math.round(2.5) == 3 en JavaScript (round(2.5) == 2 en Python !)
    assert js_round(2.5) == 3
    assert js_round(2.4) == 2


# --- Badge de vérification ---

def test_verified_badge() -> None:
    assert verified_badge(1) == {"text": "Vérifié", "css": "verified"}
    assert verified_badge(0) == {"text": "En attente", "css": "pending"}
    assert verified_badge(None)["css"] == "pending"


# --- Météo ---

def test_weather_css_seuils() -> None:
    assert weather_css(44) == "good-weather"
    assert weather_css(45) == "acceptable-weather"
    assert weather_css(65) == "acceptable-weather"
    assert weather_css(66) == "bad-weather"


def test_weather_advice_chaleur() -> None:
    # Beau temps chaud → conseil de partir tôt
    assert weather_advice("sun", 25)["text"] == "Partez de bonne heure"
    assert weather_advice("sun", 24.9)["text"] == "Parfait pour randonner"
    # La pluie à 30° ne déclenche pas le conseil chaleur
    assert weather_advice("rain", 30)["text"] == "Équipements conseillés"
    # Pictogramme inconnu → conseil "indisponible"
    assert weather_advice("inconnu", 20)["text"] == "Météo indisponible"


def test_meteo_day_label() -> None:
    # La première prévision est toujours "Aujourd'hui"
    assert meteo_day_label("2026-07-06", 0) == "Aujourd'hui"
    # 2026-07-07 est un mardi
    assert meteo_day_label("2026-07-07", 1) == "Mardi 7 juil"


def test_enrich_meteo_forecasts() -> None:
    forecasts = [
        {"date": "2026-07-06", "temp_max": 20.5, "temp_min": 16.7,
         "weather_code": 3, "picto": "cloud",
         "precipitation_sum": 0.0, "wind_speed_max": 15.2},
    ]
    (f,) = enrich_meteo_forecasts(forecasts)
    assert f["day_label"] == "Aujourd'hui"
    assert f["css"] == "good-weather"
    assert f["temp_max_label"] == "21°"       # 20.5 arrondi à la JS
    assert f["temp_min_label"] == "17°"
    assert f["precipitation_label"] is None   # pas de pluie → pas de ligne
    assert f["wind_label"] == "15 km/h"


# --- Randonnées ---

def test_duration_category_seuils() -> None:
    assert duration_category(1.9) == "court"
    assert duration_category(2) == "moyen"
    assert duration_category(4) == "moyen"
    assert duration_category(4.1) == "long"


def test_hike_trace_color() -> None:
    assert hike_trace_color(0, 1) == "hsl(187, 55%, 40%)"
    assert hike_trace_color(0, 3) == "hsl(187, 55%, 50%)"
    assert hike_trace_color(2, 3) == "hsl(187, 55%, 30%)"


def test_enrich_hike_fallbacks() -> None:
    hike = enrich_hike({"difficulte": None, "duration": 3, "distance_km": 13.0,
                        "verifie": 1, "description": None}, 0, 1)
    assert hike["difficulty_css"] == "facile"
    assert hike["difficulty_label"] == "N/A"
    assert hike["description_label"] == "Randonnée sans description"
    assert hike["summary_label"] == "13 km - 3h"


# --- Spots ---

def test_spot_category_casse_et_espaces() -> None:
    assert spot_category("CAMPING") == "payant"
    assert spot_category("camping  ") == "payant"
    assert spot_category("AIRE DE REPOS") == "gratuit"
    assert spot_category("TYPE INCONNU") == "autres"
    assert spot_category(None) == "autres"


def test_enrich_spot() -> None:
    spot = enrich_spot({"type": None, "verifie": 0, "description": None,
                        "rating": 4.2, "services": ["Eau potable", "Sauna"]})
    assert spot["type_label"] == "Bivouac"
    assert spot["category"] == "autres"
    assert spot["rating_label"] == "⭐ 4.2/5"
    assert spot["services_display"][0] == {"icon": "💧", "name": "Eau potable"}
    assert spot["services_display"][1] == {"icon": "✓", "name": "Sauna"}


# --- POI / services ---

def test_distance_label() -> None:
    assert distance_label(0.35) == "350 m"
    assert distance_label(1.2) == "1.2 km"
    assert distance_label(2.0) == "2 km"


def test_enrich_poi() -> None:
    poi = enrich_poi({"service_type": None, "distance_km": 0.5, "verifie": 1})
    assert poi["service_type_label"] == "Service"
    assert poi["distance_label"] == "500 m"
    assert poi["badge"]["css"] == "verified"


def test_poi_subtitle_accords() -> None:
    # Genre féminin
    assert poi_subtitle("vidange", 0) == "Aucune station de vidange disponible pour cette journée"
    # Genre masculin
    assert poi_subtitle("eau", 0) == "Aucun point d'eau disponible pour cette journée"
    # Singulier / pluriel
    assert poi_subtitle("eau", 1) == "1 point d'eau disponible pour cette journée"
    assert poi_subtitle("eau", 3) == "3 points d'eau disponibles pour cette journée"
    # Catégorie inconnue → libellé générique
    assert poi_subtitle("inconnu", 2) == "2 services disponibles pour cette journée"


# --- Récapitulatif ---

def test_result_day_display_complet() -> None:
    display = result_day_display({
        "day_number": 2, "hike_id": 5, "hike_name": "GR34",
        "distance_km": 13.0, "difficulte": "moyen",
        "spot_id": 7, "spot_name": "Aire du port", "spot_address": "1 rue du Quai",
        "pois": [{"name": "Folavoine", "address": "Place de l'Église"}],
    })
    assert display["day_title"] == "Jour 2"
    assert display["activity_html"] == "GR34 (13 km, moyen)"
    assert display["accommodation_html"] == "Aire du port<br><small>📍 1 rue du Quai</small>"
    assert display["services_html"] == "Folavoine <small>📍 Place de l'Église</small>"


def test_result_day_display_jour_vide() -> None:
    display = result_day_display({"day_number": 1, "hike_id": None, "spot_id": None, "pois": []})
    assert display["activity_html"] == "Pas de randonnée - Détente"
    assert display["accommodation_html"] == "Aucun spot sélectionné"
    assert display["services_html"] == "Aucun service"
