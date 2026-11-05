from datetime import date, time

from agents import choose_pepites

# Samedi 31/10/2026 à Plougonvelin : rando de 2 h, beau temps, coucher du soleil à 18 h 03.
DAY = {"day_date": date(2026, 10, 31), "city_name": "Plougonvelin", "hike_name": "Fort de Bertheaume",
       "hike_duration_h": 2, "free_time_h": 7, "sunset": time(18, 3),
       "weather": {"picto": "sun", "temp_min_c": 9, "temp_max_c": 14.4, "wind_max_kmh": 35, "precipitation_mm": 0}}

DUNES = {"id": 101, "nom": "Dunes de Corn ar Gazel", "categorie": "point_de_vue", "description": "Dunes face à l'océan.",
         "creneau": "libre", "duree_h": 1, "exterieur": 1, "distance_km": 3, "note": 8,
         "latitude": 48.55, "longitude": -4.70, "themes": ["nature", "mer"]}
CINEMA = DUNES | {"id": 40, "nom": "Cinéma Le Dauphin", "categorie": "activite", "exterieur": 0,
                  "horaires": "Vers 20 h 30", "note": 7}


def test_the_message_describes_the_day_and_numbers_the_ideas() -> None:
    message = choose_pepites.build_user_message(DAY, [DUNES, CINEMA], 2, ["Fort de Bertheaume"])
    assert "JOUR : samedi 31/10/2026" in message
    assert "RANDO DU JOUR : Fort de Bertheaume, 2 h de marche" in message
    assert "MÉTÉO PRÉVUE : ensoleillé, 9 à 14 °C, vent jusqu'à 35 km/h" in message
    assert "COUCHER DU SOLEIL : 18 h 03" in message
    assert "DÉJÀ PROPOSÉES CE JOUR (pour varier) : Fort de Bertheaume" in message
    # Vany désigne les idées par leur numéro : il ne peut pas en inventer.
    assert "[101] Dunes de Corn ar Gazel - Point de vue" in message
    # Les thèmes serviront à tenir compte des goûts du voyageur.
    assert "thèmes : nature, mer" in message
    assert "[40] Cinéma Le Dauphin - Activité · Vers 20 h 30" in message


def test_vany_sees_what_the_other_days_already_hold() -> None:
    memorial = {"nom": "Mémorial des marins", "day_date": date(2026, 11, 1), "distance_km": 2.14}
    message = choose_pepites.build_user_message(DAY, [DUNES], 1, [], [memorial])
    assert "DÉJÀ AU PROGRAMME DU SÉJOUR, LES AUTRES JOURS : Mémorial des marins (dimanche, à 2.1 km)" in message
    assert "AU PROGRAMME" not in choose_pepites.build_user_message(DAY, [DUNES], 1, [])


def test_without_forecast_vany_is_told_so() -> None:
    assert "pas encore de prévision" in choose_pepites.weather_line(None)
    assert "pas de rando" in choose_pepites.build_user_message(DAY | {"hike_name": None}, [DUNES], 1, [])


def test_vany_says_when_to_go_with_a_known_moment() -> None:
    schema = choose_pepites.choose_schema([101], 1)
    assert schema["properties"]["choix"]["items"]["properties"]["moment"]["enum"][0] == "matin"
    # Un moment inconnu n'est pas gardé : l'idée sera rangée d'après sa fiche.
    answer = {"choix": [{"id": 101, "pourquoi": "Au petit jour.", "moment": "aube"}], "coup_de_coeur": 101}
    assert choose_pepites.clean_choice(answer, [101], 1)["moment"] == {}


def test_vany_can_only_pick_from_the_numbered_ideas() -> None:
    schema = choose_pepites.choose_schema([101, 40], 2)
    assert schema["properties"]["choix"]["items"]["properties"]["id"]["enum"] == [101, 40]
    assert schema["properties"]["choix"]["maxItems"] == 2


def test_a_choice_outside_the_list_twice_or_without_a_sentence_is_dropped() -> None:
    answer = {"choix": [{"id": 999, "pourquoi": "Inventée."},
                        {"id": 101, "pourquoi": "  Coucher du soleil   à 18 h 03 juste après ta rando. ",
                         "moment": "coucher_soleil"},
                        {"id": 101, "pourquoi": "Doublon."},
                        {"id": 40, "pourquoi": ""}],
              "coup_de_coeur": 101}
    choice = choose_pepites.clean_choice(answer, [101, 40], 2)
    assert choice == {"ids": [101], "why": {101: "Coucher du soleil à 18 h 03 juste après ta rando."},
                      "moment": {101: "coucher_soleil"}, "favorite": 101}


def test_the_favorite_must_be_among_the_chosen_ideas() -> None:
    answer = {"choix": [{"id": 101, "pourquoi": "Le soleil se couche à 18 h."},
                        {"id": 40, "pourquoi": "Une séance au chaud ce soir."}], "coup_de_coeur": 7}
    assert choose_pepites.clean_choice(answer, [101, 40], 1) == {
        "ids": [101], "why": {101: "Le soleil se couche à 18 h."}, "moment": {}, "favorite": None}


def test_an_unusable_answer_lets_the_code_rank_alone() -> None:
    assert choose_pepites.clean_choice({"choix": [], "coup_de_coeur": 101}, [101], 1) is None


def test_when_vany_does_not_answer_nothing_is_raised(monkeypatch) -> None:
    class Down:
        last_run = {}

        def complete_json(self, *args):
            raise RuntimeError("quota dépassé")
    monkeypatch.setattr(choose_pepites, "make_llm_service", Down)
    assert choose_pepites.choose_pepites(DAY, [DUNES], 1) is None
