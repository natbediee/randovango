from datetime import date, datetime, timedelta

from services import pepite_service

NOW = datetime(2026, 11, 1, 12, 0)

# Dimanche 15/11/2026, rando de 5 h, spot à Morgat, pas de prévision météo.
DAY = {"day_date": date(2026, 11, 15), "hike_duration_h": 5, "weather_picto": None,
       "points": [(48.225, -4.50)]}


def idea(**fields) -> dict:
    """Une idée valable ce jour-là ; chaque test change seulement ce qu'il vérifie."""
    return {"id": 1, "nom": "Pointe de Dinan", "categorie": "point_de_vue", "latitude": 48.24,
            "longitude": -4.55, "date_debut": None, "date_fin": None, "jours_semaine": [],
            "creneau": "libre", "duree_h": 1, "exterieur": 1, "permanent": 1, "note": 9,
            "verified_at": NOW - timedelta(days=200)} | fields


def test_a_place_found_again_is_recognised_despite_punctuation_and_position() -> None:
    known = [idea(id=328, nom="Vallée du Queffleuth (boucle de Riboul Potic)", latitude=48.492, longitude=-3.83)]
    again = idea(nom="Vallée du Queffleuth, boucle de Riboul Potic", latitude=48.49, longitude=-3.86)  # 2,2 km
    assert pepite_service.same_place(again, known)["id"] == 328
    # Au-delà de 3 km, c'est un autre lieu du même nom.
    assert pepite_service.same_place(again | {"longitude": -3.90}, known) is None


def test_two_places_with_a_generic_name_must_be_very_close() -> None:
    known = [idea(id=5, nom="Lavoir", latitude=48.24, longitude=-4.55)]
    assert pepite_service.same_place(idea(nom="lavoir", latitude=48.241, longitude=-4.55), known)["id"] == 5
    assert pepite_service.same_place(idea(nom="Lavoir", latitude=48.25, longitude=-4.55), known) is None


def test_an_idea_on_the_site_of_another_day_is_not_a_new_outing() -> None:
    # Le Mémorial des marins (dimanche) et la pointe Saint-Mathieu sont à 74 m.
    memorial = {"latitude": 48.33072, "longitude": -4.77313}
    assert pepite_service.same_site_as(idea(latitude=48.33006, longitude=-4.7733), [memorial])
    assert not pepite_service.same_site_as(idea(latitude=48.3434, longitude=-4.7128), [memorial])  # Porsmilin
    assert not pepite_service.same_site_as(idea(), [])


def test_the_pepites_of_a_day_follow_the_day() -> None:
    # Le dimanche du voyage 301 : marché le matin, plage l'après-midi, mémorial au coucher du soleil.
    memorial = idea(nom="Mémorial", moment="coucher_soleil")
    plage = idea(nom="Porsmilin", moment="apres_midi")
    marche = idea(nom="Marché", moment="matin")
    cinema = idea(nom="Cinéma", moment=None, heure_debut=20.5, creneau="soiree")   # choisi avant les moments
    ordered = sorted([cinema, memorial, plage, marche], key=pepite_service.day_order)
    assert [p["nom"] for p in ordered] == ["Marché", "Porsmilin", "Mémorial", "Cinéma"]


def test_the_ideas_come_in_two_sections_each_with_its_favorite() -> None:
    far = idea(id=1, permanent=1, closeness=5, note=8)
    favorite = idea(id=2, permanent=1, closeness=9, note=7, coup_de_coeur=1)
    market = idea(id=3, permanent=0, closeness=7, note=8)
    concert = idea(id=4, permanent=0, closeness=9, note=9, coup_de_coeur=1)
    arranged = pepite_service.arrange_ideas([market, far, concert, favorite])
    assert [(i["id"], top) for i, top in arranged] == [(2, True), (1, False), (4, True), (3, False)]


def test_without_vany_only_the_timeless_section_gets_a_badge() -> None:
    # Vany n'a pas répondu : le badge « de Vany » va à la mieux notée des intemporels,
    # mais on n'en invente pas un pour une idée du séjour.
    arranged = pepite_service.arrange_ideas([idea(id=1, permanent=1, closeness=5, note=8),
                                             idea(id=2, permanent=1, closeness=9, note=9),
                                             idea(id=3, permanent=0, closeness=7, note=8)])
    assert [(i["id"], top) for i, top in arranged] == [(2, True), (1, False), (3, False)]


def test_a_search_only_runs_if_its_section_has_room() -> None:
    assert pepite_service.searches_to_run(["agenda", "lieux"], {"saison": 0, "sejour": 2}) == ["agenda"]
    assert pepite_service.searches_to_run(["agenda", "lieux"], {"saison": 3, "sejour": 0}) == ["lieux"]
    assert pepite_service.searches_to_run(["agenda"], {"saison": 0, "sejour": 0}) == []


def test_an_event_only_exists_between_its_dates() -> None:
    expo = idea(categorie="evenement", date_debut=date(2026, 11, 1), date_fin=date(2026, 11, 30))
    assert pepite_service.is_valid_on(expo, date(2026, 11, 15))
    assert not pepite_service.is_valid_on(expo, date(2026, 12, 1))


def test_a_sunday_market_is_not_proposed_on_a_monday() -> None:
    market = idea(categorie="marche", jours_semaine=[6])
    assert pepite_service.is_valid_on(market, date(2026, 11, 15))      # dimanche
    assert not pepite_service.is_valid_on(market, date(2026, 11, 16))  # lundi


def test_only_what_can_change_must_have_been_seen_recently() -> None:
    assert pepite_service.is_fresh(idea(permanent=1), NOW)              # vu il y a 200 jours
    assert not pepite_service.is_fresh(idea(permanent=0), NOW)
    assert pepite_service.is_fresh(idea(permanent=0, verified_at=NOW - timedelta(days=3)), NOW)


def test_a_long_hike_leaves_no_time_for_a_daytime_visit() -> None:
    museum = idea(creneau="journee", duree_h=2)
    assert pepite_service.fits_time(museum, hike_duration_h=5)          # 9 h + 5 h = 14 h, fini à 16 h
    assert not pepite_service.fits_time(museum, hike_duration_h=8)      # plus que 1 h avant 18 h


def test_a_fixed_start_must_come_after_the_end_of_the_hike() -> None:
    boat = idea(creneau="journee", duree_h=2, heure_debut=13.25)       # départ à 13 h 15
    assert pepite_service.fits_time(boat, hike_duration_h=4)            # rando finie à 13 h
    assert not pepite_service.fits_time(boat, hike_duration_h=5)        # ni après (14 h), ni avant (fini à 20 h 30)


def test_a_morning_visit_fits_when_the_hike_can_follow_it() -> None:
    visit = idea(creneau="journee", duree_h=1, heure_debut=11)          # 11 h - 12 h
    assert pepite_service.fits_time(visit, hike_duration_h=4)           # rando de 12 h 15 à 16 h 15
    assert not pepite_service.fits_time(visit, hike_duration_h=7)       # elle finirait à 19 h 15


def test_an_evening_event_always_fits_after_the_hike() -> None:
    assert pepite_service.fits_time(idea(creneau="soiree", duree_h=3), hike_duration_h=9)


def test_rain_rules_out_outdoor_ideas_only() -> None:
    assert not pepite_service.fits_weather(idea(exterieur=1), "rain")
    assert pepite_service.fits_weather(idea(exterieur=0), "rain")
    assert pepite_service.fits_weather(idea(exterieur=1), None)


def test_evaluate_rejects_far_or_ordinary_ideas() -> None:
    assert pepite_service.evaluate(idea(latitude=48.5), DAY, NOW) is None   # ~30 km
    assert pepite_service.evaluate(idea(note=5), DAY, NOW) is None


def test_without_forecast_an_outdoor_idea_is_to_be_checked_the_day_before() -> None:
    result = pepite_service.evaluate(idea(), DAY, NOW)
    assert result["meteo_a_verifier"] is True
    assert pepite_service.evaluate(idea(exterieur=0), DAY, NOW)["meteo_a_verifier"] is False


def test_the_closest_ideas_come_first_but_an_event_gets_a_head_start() -> None:
    near_place = pepite_service.closeness(idea(categorie="lieu"), distance=2)
    far_place = pepite_service.closeness(idea(categorie="lieu"), distance=6)
    event = pepite_service.closeness(idea(categorie="evenement"), distance=4)
    assert near_place < far_place
    assert event < near_place          # 4 km - 3 km d'avance


# Tracé GPX vers le nord : un point tous les 110 m environ, de (48.24, -4.55) à (48.25, -4.55).
TRACE = [(48.24 + i * 0.001, -4.55) for i in range(11)]


def test_a_place_within_400_m_of_a_trace_is_on_the_hike() -> None:
    assert pepite_service.trace_position(idea(latitude=48.245, longitude=-4.552), TRACE) == 5   # ~150 m
    assert pepite_service.trace_position(idea(latitude=48.245, longitude=-4.56), TRACE) is None  # ~740 m


def test_what_a_hike_of_the_stay_passes_by_is_not_a_pepite() -> None:
    assert pepite_service.evaluate(idea(), DAY | {"trip_traces": [TRACE]}, NOW) is None
    assert pepite_service.evaluate(idea(), DAY | {"trip_traces": []}, NOW) is not None
    # Un concert au bourg traversé par la rando reste une sortie à part entière.
    concert = idea(categorie="evenement", creneau="soiree", permanent=0, verified_at=NOW)
    assert pepite_service.evaluate(concert, DAY | {"trip_traces": [TRACE]}, NOW) is not None


def test_trail_tips_are_places_on_the_way_in_walking_order() -> None:
    end = idea(id=2, nom="Menhir", latitude=48.2495)
    start = idea(id=3, nom="Calvaire", categorie="lieu", latitude=48.2405)
    market = idea(id=4, nom="Marché", categorie="marche", latitude=48.245)   # pas un lieu à voir en passant
    far = idea(id=5, nom="Phare", longitude=-4.60)
    tips = pepite_service.trail_tips([end, market, far, start], TRACE)
    assert [tip["nom"] for tip in tips] == ["Calvaire", "Menhir"]


# --- Position d'une idée (locate) ------------------------------------------------

# Cas réel de Plougonvelin : l'agent avait placé le cinéma à 740 m, en mer.
DAUPHIN = {"name": "Le Dauphin", "latitude": 48.3460, "longitude": -4.7050}
PARKING = {"name": "Parking du cinéma Le Dauphin", "latitude": 48.3470, "longitude": -4.7060}


class FakeCursor:
    """Curseur qui renvoie les POI de la base ETL donnés au test."""
    def __init__(self, pois):
        self.pois = pois

    def execute(self, query, params=None):
        pass

    def fetchall(self):
        return self.pois


def test_names_are_compared_without_accents_or_punctuation() -> None:
    assert pepite_service.name_key("Cinéma « Le Dauphin » !") == "cinema le dauphin"


def test_the_place_is_found_in_the_etl_base_by_its_name() -> None:
    poi = pepite_service.match_poi("Cinéma Le Dauphin", 48.346, -4.695, [PARKING, DAUPHIN])
    assert poi is DAUPHIN       # nom contenu dans celui du lieu, et plus court écart qu'un parking
    assert pepite_service.match_poi("Le Dauphin", 48.346, -4.695, [PARKING, DAUPHIN]) is DAUPHIN  # nom identique


def test_a_short_or_distant_name_is_not_enough() -> None:
    assert pepite_service.match_poi("Port", 48.346, -4.695, [{"name": "Port de Melon", "latitude": 48.346,
                                                              "longitude": -4.70}]) is None
    assert pepite_service.match_poi("Le Dauphin", 48.50, -4.695, [DAUPHIN]) is None   # à 17 km


def test_locate_prefers_the_etl_base_then_the_address(monkeypatch) -> None:
    cinema = {"nom": "Séance au cinéma", "lieu": "Cinéma Le Dauphin", "adresse": "2 boulevard de la Mer, Plougonvelin",
              "latitude": 48.346, "longitude": -4.695}
    pepite_service.locate(FakeCursor([DAUPHIN]), cinema)
    # « Le Dauphin » est seulement contenu dans « Cinéma Le Dauphin » : position à faire revoir par l'agent.
    assert (cinema["latitude"], cinema["longitude"], cinema["position_source"]) == (48.3460, -4.7050, "base_partiel")

    monkeypatch.setattr(pepite_service, "geocode_address_ban", lambda address, lat, lon: (48.3459, -4.7049))
    cinema |= {"latitude": 48.346, "longitude": -4.695}
    pepite_service.locate(FakeCursor([]), cinema)
    assert (cinema["latitude"], cinema["position_source"]) == (48.3459, "adresse")


def test_without_base_nor_address_the_agent_estimate_is_kept_as_approximate(monkeypatch) -> None:
    monkeypatch.setattr(pepite_service, "geocode_address_ban", lambda address, lat, lon: None)
    beach = {"nom": "Plage de Trégana", "lieu": "Plage de Trégana", "adresse": None,
             "latitude": 48.35, "longitude": -4.63}
    pepite_service.locate(FakeCursor([]), beach)
    assert (beach["latitude"], beach["position_source"]) == (48.35, "agent")


def test_a_generic_poi_name_is_not_taken_for_a_precise_place() -> None:
    generic = {"name": "Point de vue", "latitude": 48.627, "longitude": -4.566}
    precise = {"name": "Pointe de Kastell Ac'h", "latitude": 48.6265, "longitude": -4.5665}
    assert pepite_service.match_poi("Point de vue de la pointe de Kastell Ac'h", 48.62, -4.56, [generic]) is None
    assert pepite_service.match_poi("Point de vue de la pointe de Kastell Ac'h", 48.62, -4.56,
                                    [generic, precise]) is precise
    assert pepite_service.match_poi("Lavoir", 48.62, -4.56, [{"name": "Lavoir", "latitude": 48.62,
                                                               "longitude": -4.56}]) is None



# --- Rattrapage ------------------------------------------------------------------

CITIES = [{"name": f"Ville {i}"} for i in range(10)]


def test_the_catch_up_skips_covered_towns_and_stops_at_the_limit() -> None:
    answers = iter(["couverte", "faite", "couverte", "faite", "faite"])
    report = pepite_service.run_catch_up(CITIES, lambda city: next(answers), limit=2)
    assert report == {"faites": 2, "echecs": 0, "arret": False}


def test_the_catch_up_stops_when_the_agent_no_longer_answers() -> None:
    # Quota épuisé à la 3e ville : trois échecs d'affilée, on n'essaie pas les 7 suivantes.
    tried = []
    def search(city):
        tried.append(city["name"])
        return "faite" if len(tried) <= 2 else "echec"
    report = pepite_service.run_catch_up(CITIES, search)
    assert report == {"faites": 2, "echecs": 3, "arret": True}
    assert len(tried) == 5


def test_the_catch_up_says_how_many_cities_are_left(caplog) -> None:
    answers = iter(["couverte", "faite", "echec"] + ["faite"] * 7)
    with caplog.at_level("INFO", logger="pepite_service"):
        pepite_service.run_catch_up(CITIES, lambda city: next(answers), limit=2)
    # Une ville couverte par une voisine n'est pas annoncée, mais elle compte dans ce qui reste.
    lines = [r.getMessage() for r in caplog.records if "rattrapage ville" in r.getMessage()]
    assert lines[0].startswith("[pépites] rattrapage ville 2/10 :") and lines[0].endswith("faite, reste au plus 8 ville(s)")
    assert "ville 3/10" in lines[1] and "en échec, reste au plus 7" in lines[1]


def test_an_isolated_failure_does_not_stop_the_catch_up() -> None:
    answers = iter(["echec", "faite", "echec", "echec", "faite"] + ["couverte"] * 5)
    report = pepite_service.run_catch_up(CITIES, lambda city: next(answers))
    assert report == {"faites": 2, "echecs": 3, "arret": False}
