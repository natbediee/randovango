from datetime import date

from agents import discover_places, find_pepites, pepite_common

DAY = {"day_date": date(2026, 11, 15), "trip_end": date(2026, 11, 17), "city_name": "Crozon",
       "has_spot": True, "spot_name": "Parking de Morgat", "points": [(48.225, -4.50), (48.18, -4.55)],
       "trip_hikes": ["Cap de la Chèvre"]}

# Une ville vue par la recherche des lieux (ETL, rattrapage) : pas de dates ni de spot.
CITY = {"city_name": "Crozon", "has_spot": False, "points": [(48.27, -4.53)], "trip_hikes": ["Cap de la Chèvre"]}


def proposal(**fields) -> dict:
    return {"nom": "Fest-noz", "categorie": "evenement", "description": "Bal breton.", "commune": "Crozon",
            "latitude": 48.24, "longitude": -4.49, "date_debut": "2026-11-15", "date_fin": None,
            "jours_semaine": [], "horaires": "Dès 21 h", "creneau": "soiree", "duree_h": 3,
            "exterieur": False, "permanent": False, "note": 9, "themes": ["fete"],
            "sources": ["https://example.org/agenda"]} | fields


# --- find_pepites : l'agenda du séjour -------------------------------------------

def test_the_agenda_message_gives_the_rest_of_the_stay() -> None:
    message = find_pepites.build_user_message(DAY, ["Pointe de Dinan"])
    # Une recherche sert à tous les jours restants du séjour, pas seulement au jour préparé.
    assert "SÉJOUR : du 15/11/2026 au 17/11/2026" in message
    assert "CENTRE DE LA RECHERCHE : Parking de Morgat (48.225, -4.5)" in message
    # Ce qu'on connaît déjà n'est pas recherché à nouveau.
    assert "- Pointe de Dinan" in message
    # Les randos ne servent qu'à repérer des lieux sur leur parcours (discover_places).
    assert "Cap de la Chèvre" not in message


# --- discover_places : les lieux d'une ville -------------------------------------

def test_the_places_message_has_no_dates_but_the_hikes_of_the_town() -> None:
    message = discover_places.build_user_message(CITY, [])
    assert "SÉJOUR" not in message
    assert "CENTRE DE LA RECHERCHE : centre de Crozon (48.27, -4.53)" in message
    assert "- Cap de la Chèvre" in message
    assert "(aucune)" in message


def test_each_agent_has_its_own_categories() -> None:
    assert discover_places.CATEGORIES == ["lieu", "point_de_vue"]
    assert "evenement" in find_pepites.CATEGORIES and "point_de_vue" not in find_pepites.CATEGORIES
    schema = pepite_common.pepite_schema(discover_places.CATEGORIES, discover_places.MAX_PROPOSALS)
    assert schema["properties"]["propositions"]["items"]["properties"]["categorie"]["enum"] == ["lieu", "point_de_vue"]


def test_each_search_agent_uses_its_own_settings(monkeypatch) -> None:
    agents = []

    class Fake:
        last_run = {}
        model = "m"

        def complete_json(self, *args):
            return {"propositions": []}

    def fake_service(agent):
        agents.append(agent)
        return Fake()
    monkeypatch.setattr(pepite_common, "make_llm_service", fake_service)
    discover_places.search_places(CITY, [])
    find_pepites.search_agenda(DAY, [])
    assert agents == ["discover_places", "find_pepites"]


# --- pepite_common : contrôle des idées -----------------------------------------

def test_the_places_search_keeps_only_what_never_changes() -> None:
    menhir = proposal(nom="Menhir de Kerloas", categorie="lieu", date_debut=None, creneau="libre", permanent=True)
    assert pepite_common.clean_proposal(menhir, permanent_only=True) is not None
    # Elle n'est pas refaite avant un an : ce qui peut changer relève de l'agenda.
    assert pepite_common.clean_proposal(menhir | {"permanent": False}, permanent_only=True) is None
    assert pepite_common.clean_proposal(menhir | {"permanent": False}) is not None


def test_an_ordinary_or_unsourced_idea_is_dropped() -> None:
    assert pepite_common.clean_proposal(proposal(note=5)) is None
    assert pepite_common.clean_proposal(proposal(sources=[])) is None


def test_an_event_needs_a_date_and_lasts_at_least_one_day() -> None:
    assert pepite_common.clean_proposal(proposal(date_debut=None)) is None
    cleaned = pepite_common.clean_proposal(proposal())
    assert cleaned["date_debut"] == cleaned["date_fin"] == date(2026, 11, 15)


def test_an_unreadable_date_drops_the_idea() -> None:
    assert pepite_common.clean_proposal(proposal(date_debut="15 novembre")) is None


def test_every_idea_carries_one_to_three_known_themes() -> None:
    themes = pepite_common.pepite_schema(find_pepites.CATEGORIES, 6)["properties"]["propositions"]["items"][
        "properties"]["themes"]
    assert themes["minItems"] == 1 and themes["maxItems"] == 3
    assert "chine" in themes["items"]["enum"] and "art" in themes["items"]["enum"]
    # La consigne explique chaque thème à l'agent.
    assert "chine = brocante, vide-grenier" in pepite_common.COMMON_RULES


def test_a_theme_given_twice_is_kept_once() -> None:
    assert pepite_common.clean_proposal(proposal(themes=["fete", "fete", "art"]))["themes"] == ["fete", "art"]


def test_dead_links_are_removed_and_live_ones_come_first() -> None:
    statuses = {"https://a.fr/devine": False, "https://b.fr/lent": None, "https://c.fr/ok": True}
    assert pepite_common.sort_sources(list(statuses), statuses) == ["https://c.fr/ok", "https://b.fr/lent"]


def test_an_idea_whose_links_all_are_dead_is_kept_without_source(monkeypatch) -> None:
    # La page a disparu, le lieu existe toujours (l'étang de la Verte Vallée, à Callac).
    monkeypatch.setattr(pepite_common, "check_links", lambda urls: {url: url.endswith("ok") for url in urls})
    kept = pepite_common.check_sources([proposal(sources=["https://x.fr/devine"]),
                                        proposal(nom="Concert", sources=["https://x.fr/devine", "https://y.fr/ok"])])
    assert [(i["nom"], i["sources"]) for i in kept] == [("Fest-noz", []), ("Concert", ["https://y.fr/ok"])]


def test_a_link_is_only_dead_if_it_fails_twice(monkeypatch) -> None:
    # Une 404 passagère au premier passage (lots en parallèle), la page existe au second.
    answers = {"https://a.fr/passager": [False, True], "https://b.fr/mort": [False, False], "https://c.fr/ok": [True]}
    monkeypatch.setattr(pepite_common, "link_status", lambda url: answers[url].pop(0))
    monkeypatch.setattr(pepite_common, "sleep", lambda seconds: None)
    assert pepite_common.check_links(list(answers)) == {
        "https://a.fr/passager": True, "https://b.fr/mort": False, "https://c.fr/ok": True}


def test_the_page_of_the_idea_comes_before_a_general_agenda() -> None:
    agenda = "https://www.cotedeslegendes.bzh/lagenda/agenda/les-evenements-culturels/"
    page = "https://www.cotedeslegendes.bzh/agenda/exposition-lenfance-des-mechants-des-vilaines-et-des-affreux/"
    name = "Exposition « L'Enfance des méchants, des vilaines et des affreux »"
    assert pepite_common.names_the_idea(page, name)
    assert not pepite_common.names_the_idea(agenda, name)
    assert pepite_common.sort_sources([agenda, page], {agenda: True, page: True}, name) == [page, agenda]
    # Un lien qui répond reste devant une page peut-être précise, mais sans réponse.
    assert pepite_common.sort_sources([page, agenda], {agenda: True, page: None}, name) == [agenda, page]
