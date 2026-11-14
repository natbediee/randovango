import sys

import pytest

from agents import find_services, service_chain
from agents.find_commerces import COMMERCES
from agents.find_restaurants import RESTAURANTS
from agents.find_supermarches import SUPERMARCHES
from agents.llm_service import passage_courant
from services import service_store

CITY = {"id": 12, "name": "Plougonvelin", "department": "Finistère", "latitude": 48.3, "longitude": -4.7}


class _Database:
    """MySQL pour le verrou : GET_LOCK rend 1 s'il est libre, 0 s'il est tenu par un autre lancement."""
    def __init__(self, free=True):
        self.free, self.queries, self.opened, self.closed = free, [], 0, 0

    def connect(self):
        self.opened += 1
        return self

    def cursor(self):
        return self

    def execute(self, sql, params=None):
        self.queries.append(sql)

    def fetchone(self):
        return (int(self.free),) if "GET_LOCK" in self.queries[-1] else (1,)

    def close(self):
        pass

    def disconnect(self, connection):
        self.closed += 1


@pytest.fixture(autouse=True)
def database(monkeypatch):
    """Aucun test n'ouvre de vraie connexion : le verrou est demandé à cette base factice, libre par défaut."""
    fake = _Database()
    monkeypatch.setattr(find_services.MySQLUtils, "connect", staticmethod(fake.connect))
    monkeypatch.setattr(find_services.MySQLUtils, "disconnect", staticmethod(fake.disconnect))
    return fake


def _passage(monkeypatch):
    """La chaîne sans agent : note la catégorie cherchée, le passage en cours, et ce qui serait enregistré."""
    calls = {"searched": [], "saved": [], "resumed": []}

    def search(category, city, resume=None):
        calls["searched"].append((category.key, city["name"], passage_courant()))
        calls["resumed"].append(resume)
        return {category.key: [{"nom": "Riboul"}]}

    monkeypatch.setattr(service_chain, "search_commune", search)
    monkeypatch.setattr(service_store, "save_commune", lambda category, *args: calls["saved"].append(category.key) or {"fiches": 1})
    monkeypatch.setattr(find_services, "model_of", lambda agent: "modele")
    return calls


def test_a_passage_runs_every_category_under_one_identifier(monkeypatch):
    """Un passage cherche puis enregistre chaque catégorie de la commune, toutes sous le même identifiant."""
    calls = _passage(monkeypatch)
    results = find_services.run_passage(CITY)
    assert [key for key, _, _ in calls["searched"]] == ["restaurants", "commerces", "supermarches"] == calls["saved"]
    assert {passage for _, _, passage in calls["searched"]} == {results["passage"]} and len(results["passage"]) == 32
    assert results["restaurants"] == results["commerces"] == results["supermarches"] == {"fiches": 1}
    assert passage_courant() is None


def test_two_passages_have_two_identifiers(monkeypatch):
    """Deux passages de la même commune n'ont jamais le même identifiant."""
    _passage(monkeypatch)
    assert find_services.run_passage(CITY)["passage"] != find_services.run_passage(CITY)["passage"]


def test_the_trial_mode_writes_nothing_in_the_database(monkeypatch):
    """Avec --essai, toutes les catégories sont cherchées mais rien n'est enregistré en base."""
    calls = _passage(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["find_services", "--ville", "Plougonvelin", "--essai"])
    monkeypatch.setattr(service_store, "load_city", lambda name: CITY)
    find_services.main()
    assert calls["saved"] == [] and len(calls["searched"]) == len(find_services.CATEGORIES)


def test_one_category_can_be_asked_alone(monkeypatch):
    """Avec --categorie, seule la catégorie demandée passe."""
    calls = _passage(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["find_services", "--ville", "Plougonvelin", "--categorie", "commerces"])
    monkeypatch.setattr(service_store, "load_city", lambda name: CITY)
    find_services.main()
    assert calls["saved"] == ["commerces"]


def test_a_commune_asked_twice_is_searched_once(monkeypatch):
    """--ville Morgat --ville Le Fret : deux villes de Crozon, un seul passage payé."""
    crozon = {"id": 57, "name": "Crozon", "commune": "Crozon", "insee": "29042", "department": "Finistère",
              "latitude": 48.25, "longitude": -4.49}
    calls = _passage(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["find_services", "--ville", "Morgat", "--ville", "Le Fret", "--essai", "--categorie", "restaurants"])
    monkeypatch.setattr(service_store, "load_city", lambda name: crozon)
    find_services.main()
    assert [(key, name) for key, name, _ in calls["searched"]] == [("restaurants", "Crozon")]


def test_every_category_of_the_chain_is_known_to_the_supervision():
    """La supervision connaît toutes les catégories de la chaîne, pour écrire la fiche d'un service confirmé."""
    from services.supervision import services_review as review
    assert review.CATEGORIES == {RESTAURANTS.source: RESTAURANTS, COMMERCES.source: COMMERCES, SUPERMARCHES.source: SUPERMARCHES}


# --- Reprendre un passage arrêté en route ---

def test_a_resumed_launch_searches_only_what_was_stopped(monkeypatch):
    """Avec --reprendre, seule la catégorie dont le passage s'est arrêté en route est cherchée, à partir de son fichier ; les autres ne sont pas repayées."""
    calls = _passage(monkeypatch)
    stopped = {"commune": "Plougonvelin", "zones": [{"zone": {}, "final": []}]}
    monkeypatch.setattr(service_chain, "interrupted_trace", lambda category, city: stopped if category.key == "restaurants" else None)
    results = find_services.run_passage(CITY, trial=True, resume=True)
    assert [key for key, _, _ in calls["searched"]] == ["restaurants"] and calls["resumed"] == [stopped]
    assert results["commerces"] == {"passe": "aucun passage arrêté à reprendre"}


def test_a_big_city_without_register_stops_the_launch(monkeypatch):
    """Si le registre d'une grande ville n'a pas pu être lu, le lancement s'arrête avec un message au lieu de payer une recherche sans zones."""
    def unreadable(category, city, resume=None):
        raise service_chain.RegisterUnavailable("Marseille : registre illisible")

    monkeypatch.setattr(service_chain, "search_commune", unreadable)
    monkeypatch.setattr(service_store, "load_city", lambda name: CITY)
    monkeypatch.setattr(sys, "argv", ["find_services", "--ville", "Marseille", "--essai"])
    with pytest.raises(SystemExit):
        find_services.main()


# --- Rejouer les règles sur les fichiers déjà payés ---

def _replay(monkeypatch, version):
    """
    Un fichier de Plougonvelin par catégorie, écrit à cette version des consignes. Rend ce qui est enregistré
    (catégorie, essai), et les fichiers du passage.
    """
    saved = []
    files = {category.key: {"commune": "Plougonvelin", "version": version(category), "registre": None, "final": []}
             for category in find_services.CATEGORIES}
    monkeypatch.setattr(service_chain, "latest_traces", lambda category: {"Plougonvelin": files[category.key]})
    monkeypatch.setattr(service_chain, "search_commune", lambda category, city, resume=None: pytest.fail("un rejeu ne cherche rien"))
    monkeypatch.setattr(service_store, "save_commune",
                        lambda category, city, answer, version, model, trial: saved.append((category.key, trial)) or {"fiches": 0})
    monkeypatch.setattr(service_store, "load_city", lambda name: CITY)
    monkeypatch.setattr(find_services, "model_of", lambda agent: "modele")
    return saved, files


def test_a_replay_saves_again_without_any_agent(monkeypatch):
    """--rejouer enregistre de nouveau chaque catégorie depuis son fichier, sans appeler d'agent, tous les passages par défaut."""
    saved, _ = _replay(monkeypatch, lambda category: category.prompt_version)
    monkeypatch.setattr(sys, "argv", ["find_services", "--rejouer"])
    find_services.main()
    assert saved == [("restaurants", False), ("commerces", False), ("supermarches", False)]


def test_a_file_of_older_instructions_is_replayed_only_as_a_trial(monkeypatch):
    """Un fichier écrit avec d'anciennes consignes n'est pas réécrit en base (sa grille de catégories a changé) : il se rejoue à l'essai."""
    saved, files = _replay(monkeypatch, lambda category: category.prompt_version - 1)
    results = find_services.replay_passage(CITY, files)
    assert saved == [] and "à l'essai seulement" in results["restaurants"]["passe"]
    find_services.replay_passage(CITY, files, trial=True)
    assert saved == [("restaurants", True), ("commerces", True), ("supermarches", True)]


def test_a_category_without_file_is_passed(monkeypatch):
    """Une catégorie qui n'a jamais cherché cette commune n'a pas de fichier : le rejeu la passe, les autres sont rejouées."""
    saved, files = _replay(monkeypatch, lambda category: category.prompt_version)
    results = find_services.replay_passage(CITY, {**files, "commerces": None})
    assert saved == [("restaurants", False), ("supermarches", False)] and results["commerces"] == {"passe": "aucun fichier"}


def test_a_passage_made_under_a_town_name_is_replayed_under_that_name(monkeypatch):
    """Les passages d'avant le 8 novembre 2026 portent le nom de la ville : Morgat et Le Fret, deux villes de Crozon, sont rejoués chacun avec son fichier."""
    saved = []
    crozon = {**CITY, "id": 57, "name": "Crozon", "commune": "Crozon", "insee": "29042"}
    files = {name: {"commune": name, "version": 1, "registre": None, "final": [{"nom": name}]} for name in ("Le Fret", "Morgat")}
    monkeypatch.setattr(service_chain, "latest_traces", lambda category: files)
    monkeypatch.setattr(service_chain, "replay_rules", lambda category, trace: {"file": trace["commune"], "preuve_a_chercher": []})
    monkeypatch.setattr(service_store, "save_commune",
                        lambda category, city, answer, version, model, trial: saved.append((city["name"], answer["file"])) or {})
    monkeypatch.setattr(service_store, "load_city", lambda name: crozon)
    monkeypatch.setattr(find_services, "model_of", lambda agent: "modele")
    monkeypatch.setattr(sys, "argv", ["find_services", "--rejouer", "--essai", "--categorie", "restaurants"])
    find_services.main()
    assert saved == [("Crozon", "Le Fret"), ("Crozon", "Morgat")]


# --- Un seul passage à la fois ---

def test_a_passage_holds_the_lock_and_gives_it_back(monkeypatch, database):
    """Un passage prend le verrou de MySQL au début et le rend à la fin."""
    _passage(monkeypatch)
    find_services.run_passage(CITY)
    assert [query.split("(")[0] for query in database.queries] == ["SELECT GET_LOCK", "SELECT RELEASE_LOCK"]
    assert database.opened == database.closed == 1 and find_services._lock_connection is None


def test_a_second_launch_stops_at_once_and_searches_nothing(monkeypatch, database):
    """Si un autre lancement tient le verrou, celui-ci s'arrête tout de suite sans rien chercher."""
    calls = _passage(monkeypatch)
    database.free = False
    with pytest.raises(find_services.PassageRunning):
        find_services.run_passage(CITY)
    monkeypatch.setattr(sys, "argv", ["find_services", "--ville", "Plougonvelin"])
    monkeypatch.setattr(service_store, "load_city", lambda name: CITY)
    with pytest.raises(SystemExit):
        find_services.main()
    assert calls["searched"] == [] and database.closed == database.opened and find_services._lock_connection is None


def test_a_launch_keeps_one_lock_for_all_its_communes(monkeypatch, database):
    """Un lancement de plusieurs communes prend le verrou une seule fois et le garde jusqu'à la dernière."""
    _passage(monkeypatch)
    cities = {"Plougonvelin": CITY, "Le Conquet": {**CITY, "id": 13, "name": "Le Conquet"}}
    monkeypatch.setattr(sys, "argv", ["find_services", "--ville", "Plougonvelin", "--ville", "Le Conquet", "--essai"])
    monkeypatch.setattr(service_store, "load_city", lambda name: cities[name])
    find_services.main()
    assert sum("GET_LOCK" in query for query in database.queries) == 1 and database.opened == 1
    assert database.queries[-1].startswith("SELECT RELEASE_LOCK")


def test_the_lock_is_given_back_when_a_passage_fails(monkeypatch, database):
    """Le verrou est rendu même quand le passage échoue."""
    monkeypatch.setattr(service_chain, "search_commune", lambda category, city, resume=None: 1 / 0)
    with pytest.raises(ZeroDivisionError):
        find_services.run_passage(CITY)
    assert database.queries[-1].startswith("SELECT RELEASE_LOCK") and find_services._lock_connection is None
