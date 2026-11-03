"""Tests du module de présentation (fonctions pures, sans base de données)."""

from datetime import date

from utils.display_utils import (
    pepite_day_texts,
    pepite_display,
    pepite_line_html,
    pepite_news_text,
    pepite_nothing_texts,
    pepite_section,
    distance_label,
    hike_distance_label,
    hike_schedule_label,
    duration_category,
    enrich_hike,
    enrich_meteo_forecasts,
    enrich_poi,
    a_savoir_on,
    enrich_spot,
    with_a_savoir,
    spot_services_display,
    spot_name_label,
    spot_description_label,
    spot_description_html,
    SPOT_SERVICE_CATEGORIES,
    hike_trace_color,
    js_num,
    js_round,
    meteo_day_label,
    poi_subtitle,
    result_day_display,
    spot_category,
    trail_tips_html,
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
    assert verified_badge(0) == {"text": "Non vérifié", "css": "pending"}
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
                        "rating": 4.2, "services": [
                            {"name": "Eau potable", "category": "drinking_water"},
                            {"name": "Sauna", "category": None},
                        ]})
    assert spot["type_label"] == "Bivouac"
    assert spot["category"] == "autres"
    assert spot["rating_label"] == "⭐ 4.2/5"
    assert spot["services_display"][0] == {"icon": "💧", "name": "Eau potable"}
    # Catégorie inconnue : le nom Park4Night est gardé, rien ne disparaît.
    assert spot["services_display"][1] == {"icon": "✓", "name": "Sauna"}


def test_spot_services_display_merges_services_of_the_same_category() -> None:
    badges = spot_services_display([
        {"name": "Pêche à pied", "category": "fishing"},
        {"name": "Coins de pêche", "category": "fishing"},
        {"name": "Eaux usées", "category": "sanitary_dump_station"},
        {"name": "Eaux noires", "category": "sanitary_dump_station"},
        {"name": "Départ de randonnées", "category": "hiking"},
    ])
    # Un badge par catégorie, libellé français, équipements avant activités.
    assert [b["name"] for b in badges] == ["Vidange", "Randonnée", "Pêche"]


def test_every_mapped_service_category_has_a_french_label() -> None:
    # Toute catégorie produite par le mapping P4N doit avoir son libellé,
    # sinon ses services retomberaient sur le nom brut.
    from utils.service_utils import SERVICE_CATEGORY_MAP
    assert set(SERVICE_CATEGORY_MAP.values()) <= SPOT_SERVICE_CATEGORIES.keys()


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
    # POI sans catégorie ni type : marqueur générique et libellé de repli.
    assert display["services_html"] == (
        '<i class="fas fa-map-marker-alt"></i> Folavoine'
        ' <small class="muted">· service</small>'
        "<br><small>📍 Place de l'Église</small>"
    )


def test_result_day_display_service_montre_icone_et_type() -> None:
    # Un nom seul ne dit pas de quoi il s'agit : la ligne porte l'icône de la
    # catégorie et le type précis du service.
    display = result_day_display({
        "day_number": 1, "hike_id": None, "spot_id": None,
        "pois": [{"name": "Glenn", "category": "restauration", "service_type": "Restaurant"}],
    })
    assert display["services_html"] == (
        '<i class="fas fa-utensils"></i> Glenn <small class="muted">· Restaurant</small>'
    )


def test_result_day_display_service_ne_repete_pas_le_nom() -> None:
    # Quand le type ne fait que répéter le nom ("Plage" / "Plage"), on affiche le
    # libellé de catégorie à la place plutôt que deux fois le même mot.
    display = result_day_display({
        "day_number": 1, "hike_id": None, "spot_id": None,
        "pois": [{"name": "Plage", "category": "culture", "service_type": "plage"}],
    })
    assert display["services_html"] == (
        '<i class="fas fa-camera"></i> Plage <small class="muted">· site culturel</small>'
    )


def test_result_day_display_jour_vide() -> None:
    display = result_day_display({"day_number": 1, "hike_id": None, "spot_id": None, "pois": []})
    assert display["activity_html"] == "Pas de randonnée - Détente"
    assert display["accommodation_html"] == "Aucun spot sélectionné"
    assert display["services_html"] == "Aucun service"


# --- Nom affiché d'un spot ---

def test_spot_name_label_builds_a_fallback_without_the_house_number() -> None:
    assert spot_name_label("139 Mechou Kamm Doun", "Plouguerneau", "…",
                           "PARKING JOUR ET NUIT") == "Parking · Mechou Kamm Doun"
    assert spot_name_label("33-35 Rue du Manoir", None, "…",
                           "AIRE CC STAT. GRATUIT") == "Aire camping-car · Rue du Manoir"
    assert spot_name_label("54B Route de Plestin", None, "…",
                           "PARKING JOUR ET NUIT") == "Parking · Route de Plestin"


def test_spot_name_label_keeps_a_label_that_already_names_the_place() -> None:
    assert spot_name_label("Camping Kermaléro", None, "…", "CAMPING") == "Camping Kermaléro"


def test_spot_name_label_falls_back_on_the_city_then_the_raw_name() -> None:
    assert spot_name_label(None, "Brest", "(29200) Brest -", "PARKING JOUR ET NUIT") == "Parking · Brest"
    assert spot_name_label(None, None, "(29200) Brest -", None) == "(29200) Brest -"
    assert spot_name_label(None, None, None, None) is None


def test_spot_description_label() -> None:
    assert spot_description_label("Parking calme.", "parking ok", 18) == "Parking calme."
    # Harmonisé mais vide : rien à afficher, le titre et les badges suffisent.
    assert spot_description_label(None, "Camping les Pins", 18) == ""
    # Pas encore harmonisé : texte d'origine.
    assert spot_description_label(None, "parking ok", None) == "parking ok"
    assert spot_description_label(None, None, None) == "Aucune description disponible"


def test_spot_description_html_marks_what_to_know_and_escapes() -> None:
    html = spot_description_html("Aire <calme>.\n\nÀ savoir : l'aire est en pente.")
    assert html == ("Aire &lt;calme&gt;.\n\n<strong class=\"spot-warning\">À savoir :</strong>"
                    " l&#x27;aire est en pente.")
    # Seul le libellé en début de paragraphe est mis en valeur.
    assert "<strong" not in spot_description_html("Voir ce qui est à savoir : rien.")


def test_day_only_parkings_are_excluded_and_hidden() -> None:
    # "Parking jour uniquement" : on ne peut pas y dormir, ce n'est pas un spot pour Randovango.
    # Pas chargé s'il est nouveau, masqué s'il était déjà en base.
    from utils.display_utils import EXCLUDED_SPOT_TYPES, HIDDEN_SPOT_TYPES
    assert "PARKING JOUR UNIQUEMENT" in EXCLUDED_SPOT_TYPES
    assert set(EXCLUDED_SPOT_TYPES) <= set(HIDDEN_SPOT_TYPES)


# --- Les pépites de Vany ----------------------------------------------------

def _pepite(**fields) -> dict:
    return {"id": 7, "nom": "Fest-noz", "categorie": "evenement", "description": "Bal breton.",
            "horaires": "Dès 21 h", "distance_km": 6, "duree_h": 3, "exterieur": 0,
            "latitude": 48.24, "longitude": -4.49, "statut": "proposee",
            "sources": ["https://www.ouest-france.fr/agenda/1"]} | fields


def test_pepite_display_builds_the_meta_line_and_source() -> None:
    shown = pepite_display(_pepite(), top=True)
    assert shown["type_label"] == "Événement"
    assert shown["meta_label"] == "Dès 21 h · à 6 km · 3 h sur place · en intérieur"
    # Le tarif est visible avant d'ajouter une sortie payante.
    assert pepite_display(_pepite(tarif="10 €"))["meta_label"].startswith("Dès 21 h · 10 € · à 6 km")
    assert shown["source_label"] == "ouest-france.fr"
    assert shown["top"] is True
    # Une idée ajoutée à la journée est signalée (plusieurs peuvent l'être).
    assert shown["added"] is False
    assert pepite_display(_pepite(statut="choisie"))["added"] is True


def test_vany_sentence_is_shown_only_when_vany_chose() -> None:
    assert pepite_display(_pepite(pourquoi="Parfait après ta rando."))["why"] == "Parfait après ta rando."
    assert pepite_display(_pepite())["why"] == ""


def test_only_a_position_found_by_the_code_is_shown_as_exact() -> None:
    assert pepite_display(_pepite(position_source="base"))["position_approx"] is False
    assert pepite_display(_pepite(position_source="adresse"))["position_approx"] is False
    assert pepite_display(_pepite(position_source="agent"))["position_approx"] is True
    assert pepite_display(_pepite())["position_approx"] is True     # idée d'avant le recalage


def test_pepite_display_keeps_only_web_links() -> None:
    shown = pepite_display(_pepite(sources=["javascript:alert(1)"]))
    assert shown["source_url"] is None and shown["source_label"] == ""


def test_pepite_day_texts_name_the_day_and_the_free_time() -> None:
    texts = pepite_day_texts(date(2026, 11, 15), 5, 4)
    assert texts["title"] == "Les pépites de Vany pour ton dimanche"
    assert texts["intro"].startswith("Après tes 5 h de rando, il te reste environ 4 h en journée.")
    assert pepite_day_texts(date(2026, 11, 15), 0, 9)["intro"].startswith("Journée sans rando")


def test_pepite_line_escapes_the_name_coming_from_the_web() -> None:
    assert "&lt;b&gt;" in pepite_line_html({"nom": "<b>Fest-noz</b>"})


def test_result_day_shows_every_added_idea_with_the_services() -> None:
    display = result_day_display({"day_number": 1, "pois": [],
                                  "pepites": [{"nom": "Fest-noz"}, {"nom": "Cinéma Le Dauphin"}]})
    assert display["services_html"].startswith("Aucun service<br>")
    assert display["services_html"].count("pepite-icon") == 2


def test_pepite_nothing_texts_names_the_day() -> None:
    assert pepite_nothing_texts(date(2026, 10, 31))["title"] == "Pas de pépite pour ton samedi"


def test_trail_tips_appear_under_the_hike_escaped() -> None:
    assert trail_tips_html([]) == ""
    display = result_day_display({"day_number": 1, "hike_id": 1, "hike_name": "Aber Ildut", "distance_km": 12,
                                  "difficulte": "Moyen", "pois": [],
                                  "trail_tips": [{"nom": "Port goémonier"}, {"nom": "<i>Belvédère</i>"}]})
    assert "En chemin : Port goémonier · &lt;i&gt;Belvédère&lt;/i&gt;" in display["activity_html"]


def test_a_spot_near_the_hike_is_on_the_way() -> None:
    assert hike_distance_label(0.15) == "Sur ta rando · 150 m du tracé"
    assert hike_distance_label(1.21644) == "À 1.2 km de ta rando"
    assert hike_distance_label(0.101) == "Sur ta rando · 100 m du tracé"
    assert hike_distance_label(None) == ""
    spot = enrich_spot({"type": "Parking", "hike_distance_km": 0.4})
    assert spot["on_hike"] is True
    assert enrich_spot({"type": "Parking", "hike_distance_km": 0.6})["on_hike"] is False
    assert enrich_spot({"type": "Parking"})["on_hike"] is False      # pas de rando ce jour-là


def test_the_hike_is_assumed_to_start_at_nine() -> None:
    assert hike_schedule_label(2) == "Départ conseillé vers 9 h, retour vers 11 h"
    assert hike_schedule_label(2.5) == "Départ conseillé vers 9 h, retour vers 11 h 30"
    assert hike_schedule_label(None) == ""


def test_a_pepite_is_timeless_or_tied_to_the_stay() -> None:
    assert pepite_section({"permanent": 1}) == "saison"
    assert pepite_section({"permanent": 0}) == "sejour"


def test_the_bottom_bar_says_what_vany_found() -> None:
    assert pepite_news_text(2, date(2026, 11, 2), 1) == "Vany a trouvé 2 idées pour ton lundi, dont un coup de cœur"
    assert pepite_news_text(2, date(2026, 11, 2), 0) == "Vany a trouvé 2 idées pour ton lundi"
    assert pepite_news_text(1, date(2026, 11, 2), 1) == "Vany a trouvé 1 idée pour ton lundi"


def test_a_service_shows_the_name_of_its_site() -> None:
    assert enrich_poi({"url": "https://www.intermarche.com/magasin/29"})["url_label"] == "intermarche.com"
    assert enrich_poi({"url": None})["url_label"] == ""
    # OSM donne parfois l'adresse sans protocole : le lien renverrait vers notre propre site.
    poi = enrich_poi({"url": "www.labasebrest.com"})
    assert (poi["url"], poi["url_label"]) == ("https://www.labasebrest.com", "labasebrest.com")


def test_a_seasonal_sentence_only_shows_during_its_period() -> None:
    items = [{"texte": "3 nuits.", "debut": "06-15", "fin": "09-15"}, {"texte": "7 nuits.", "debut": "09-16", "fin": "06-14"},
             {"texte": "Chiens interdits.", "debut": None, "fin": "09-30"}, {"texte": "Barre de 2 m.", "debut": None, "fin": None}]
    assert a_savoir_on(items, date(2026, 8, 1)) == ["3 nuits.", "Chiens interdits.", "Barre de 2 m."]
    # La période de 7 nuits passe le 31 décembre ; les chiens sont de nouveau admis après le 30/09.
    assert a_savoir_on(items, date(2026, 11, 2)) == ["7 nuits.", "Barre de 2 m."]
    assert a_savoir_on(items, date(2027, 1, 15)) == ["7 nuits.", "Chiens interdits.", "Barre de 2 m."]


def test_the_reworked_a_savoir_replaces_the_old_one() -> None:
    old = "Aire de 28 places.\n\nÀ savoir : inaccessible le 30 décembre 2025."
    assert with_a_savoir(old, ["Wifi en panne."]) == "Aire de 28 places.\n\nÀ savoir : Wifi en panne."
    assert with_a_savoir(old, []) == "Aire de 28 places."
    assert with_a_savoir("Aire simple.", ["Barre de 2 m."]) == "Aire simple.\n\nÀ savoir : Barre de 2 m."
    assert with_a_savoir("", ["Barre de 2 m."]) == "À savoir : Barre de 2 m."
