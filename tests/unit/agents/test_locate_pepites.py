from agents import locate_pepites

# La chapelle de Brendaouez, à Guissény : estimation de l'agent de recherche.
CHAPEL = {"id": 407, "nom": "Chapelle Notre-Dame de Brendaouez et sa fontaine",
          "lieu": "Chapelle Notre-Dame de Brendaouez", "adresse": None, "commune": "Guissény",
          "latitude": 48.631, "longitude": -4.409}
MERIMEE = "https://pop.culture.gouv.fr/notice/merimee/PA00089994"


def answer(**fields) -> dict:
    return {"id": 407, "latitude": 48.6352, "longitude": -4.4075, "source": MERIMEE,
            "nom_source": "Chapelle Notre-Dame de Brendaouez"} | fields


def test_the_message_numbers_each_place_with_its_town() -> None:
    message = locate_pepites.build_user_message([CHAPEL])
    assert ("[407] Chapelle Notre-Dame de Brendaouez (« Chapelle Notre-Dame de Brendaouez et sa fontaine »),"
            " commune : Guissény") in message


def test_a_position_copied_from_a_cited_page_is_kept() -> None:
    assert locate_pepites.clean_position(answer(), CHAPEL) == (48.6352, -4.4075, MERIMEE)


def test_a_position_without_page_is_dropped() -> None:
    assert locate_pepites.clean_position(answer(source=None), CHAPEL) is None
    assert locate_pepites.clean_position(answer(latitude=None), CHAPEL) is None


def test_a_search_results_page_proves_nothing() -> None:
    # Le pilote : « chapelle Guisseny » sur Nominatim a donné une autre chapelle, à 1,9 km.
    search = "https://nominatim.openstreetmap.org/search?q=chapelle%20Guiss%C3%A9ny&format=json"
    assert locate_pepites.clean_position(answer(source=search), CHAPEL) is None
    assert locate_pepites.is_search_page("https://www.google.com/maps?q=Brendaouez")
    assert not locate_pepites.is_search_page(MERIMEE)


def test_the_page_must_name_the_place() -> None:
    assert locate_pepites.clean_position(answer(nom_source="Église Saint-Sezny"), CHAPEL) is None
    # Un nom générique (« Lavoir ») n'a pas de mot propre à retrouver.
    lavoir = CHAPEL | {"nom": "Lavoir", "lieu": "Lavoir"}
    assert locate_pepites.clean_position(answer(nom_source="Lavoir communal"), lavoir) is not None


def test_a_position_too_far_from_the_estimate_is_a_namesake() -> None:
    assert locate_pepites.clean_position(answer(latitude=48.70), CHAPEL) is None   # à 7,7 km


def test_the_agent_can_only_answer_about_the_numbered_places() -> None:
    schema = locate_pepites.locate_schema([407, 12])
    assert schema["properties"]["positions"]["items"]["properties"]["id"]["enum"] == [407, 12]


def test_only_checked_positions_come_back(monkeypatch) -> None:
    class Fake:
        last_run = {}

        def complete_json(self, *args):
            return {"positions": [answer(), answer(id=12)]}       # 12 : un lieu qu'on n'a pas demandé
    monkeypatch.setattr(locate_pepites, "make_llm_service", Fake)
    assert locate_pepites.locate_places([CHAPEL]) == {407: (48.6352, -4.4075, MERIMEE)}
