"""Tests des fonctions pures du carnet de voyage (backend/services/pdf_service.py).

Le rendu complet (render_trip_pdf_html) n'est pas testé ici : il dépend de MongoDB
(tracés GPX) et des tuiles OpenStreetMap. On couvre le formatage français, les
textes composés à partir des données du séjour et le balisage des descriptifs.
"""
from services.pdf_service import (
    _cover_subtitle,
    _fr_int,
    _fr_measure,
    _fr_number,
    _highlight_brackets,
    _long_date,
    _trip_totals,
    vany_note,
)
from datetime import date


# --- Formatage français ---

def test_fr_number_virgule_et_milliers_insecables() -> None:
    assert _fr_number(3.0, 1) == "3,0"
    # Note park4night arrondie à une décimale pour l'affichage
    assert _fr_number(4.38, 1) == "4,4"
    # Milliers séparés par une espace insécable (U+00A0), pour ne pas couper "1 072 m"
    assert _fr_number(1072) == "1 072"


def test_fr_int_arrondit() -> None:
    assert _fr_int(363.0) == "363"
    assert _fr_int(None) == ""


def test_fr_measure_garde_une_decimale_utile() -> None:
    # Une mesure entière ne s'affiche pas "13,0"...
    assert _fr_measure(13.0) == "13"
    # ... mais la décimale est conservée quand elle existe
    assert _fr_measure(13.5) == "13,5"


def test_long_date_en_francais() -> None:
    assert _long_date(date(2026, 7, 15)) == "mercredi 15 juillet 2026"
    # La date d'édition du carnet se passe du jour de la semaine
    assert _long_date(date(2026, 7, 15), weekday=False) == "15 juillet 2026"


# --- Descriptifs d'étape ---

def test_highlight_brackets_distingue_avertissements_et_notes() -> None:
    html = _highlight_brackets("Suivre la route sur 175 m [prudence !] puis [fontaine].")
    assert '<span class="step__caution">[prudence !]</span>' in html
    assert '<span class="step__note">[fontaine]</span>' in html


def test_highlight_brackets_laisse_le_texte_sans_crochets_intact() -> None:
    assert _highlight_brackets("Prendre à gauche.") == "Prendre à gauche."


# --- Totaux et couverture ---

def test_trip_totals_additionne_les_jours() -> None:
    totals = _trip_totals([
        {"hike_id": 1, "distance_km": 13.0, "elevation_gain_m": 363, "spot_id": 5},
        {"hike_id": 2, "distance_km": 26.0, "elevation_gain_m": 709, "spot_id": 6},
        # Journée détente sans rando ni spot : comptée en jours seulement
        {"hike_id": None, "distance_km": None, "elevation_gain_m": None, "spot_id": None},
    ])
    assert totals == {"days": 3, "distance_km": 39.0, "elevation_m": 1072, "nights": 2, "hikes": 2}


def test_cover_subtitle_situe_le_sejour() -> None:
    plan = {"city_name": "Telgruc-sur-Mer", "city_department": "Finistère", "city_region": "Bretagne"}
    totals = {"days": 2, "hikes": 2, "nights": 2}
    subtitle = _cover_subtitle(plan, totals)
    assert subtitle == ("2 jours en van autour de Telgruc-sur-Mer - Finistère, Bretagne. "
                        "2 randonnées, 2 spots pour la nuit et les services utiles à proximité.")


def test_cover_subtitle_sans_departement_ni_region() -> None:
    subtitle = _cover_subtitle({"city_name": "Brest"}, {"days": 1, "hikes": 1, "nights": 0})
    assert subtitle == "1 jour en van autour de Brest. 1 randonnée et les services utiles à proximité."


# --- Le mot de Vany ---

def test_vany_note_conseille_les_marees_au_bord_de_mer() -> None:
    days = [{"hike_name": "Sentier des falaises", "difficulte": "Facile"}]
    note = vany_note({"city_name": "Crozon"}, days, {"days": 1, "elevation_m": 120})
    assert note["title"] == "Bonne route autour de Crozon !"
    assert "marée" in note["text"]


def test_vany_note_enchaine_plusieurs_conseils() -> None:
    days = [
        {"hike_name": "Tour de la plage", "difficulte": "Difficile"},
        {"hike_name": "Ménez-Hom", "difficulte": "Moyen"},
    ]
    note = vany_note({"city_name": "Telgruc-sur-Mer"}, days, {"days": 2, "elevation_m": 1072})
    # Trois conseils réunis en une phrase : "A, B et C"
    assert "marée" in note["text"]
    assert "1 072 m de montée" in note["text"]
    assert " et pars de bonne heure" in note["text"]


def test_vany_note_repli_quand_rien_ne_se_distingue() -> None:
    days = [{"hike_name": "Boucle du bourg", "difficulte": "Facile"}]
    note = vany_note({"city_name": "Rennes"}, days, {"days": 1, "elevation_m": 80})
    assert "flâner" in note["text"]
    assert note["text"].endswith("On se retrouve sur RandoVanGo pour le prochain voyage.")
