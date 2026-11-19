"""
Les passages d'une chaîne d'agents lancés depuis la supervision (services/passage_service.py, issue #204).

Aucune base ni aucun agent : la trace des passages est gardée dans un dictionnaire (_Store), et la chaîne des services
est remplacée par une chaîne simulée, qui peut échouer sur la catégorie qu'on lui dit.
"""
from datetime import datetime

import pytest

from agents.find_services import PassageRunning
from agents.llm_service import LLMTimeout, LLMUnavailable, passage_courant
from services import passage_queue, passage_service, passage_store
from services.passage_service import PassageConflict

CITY = {"id": 12, "name": "Guidel", "commune": "Guidel", "insee": "56078"}


class _Store:
    """La trace des passages en mémoire, avec les mêmes fonctions que passage_store, et les appels de llm_calls."""
    def __init__(self):
        self.passages, self.parts, self.calls = {}, {}, {}

    def insert_passage(self, passage_id, chain, city_id, origin, parts, resumed_from=None, status=passage_store.QUEUED):
        self.passages[passage_id] = {"passage_id": passage_id, "chain": chain, "city_id": city_id, "origin": origin,
                                     "status": status, "requested_at": datetime(2026, 11, 19, 10),
                                     "started_at": None, "finished_at": None, "error": None,
                                     "resumed_from": resumed_from, "city_name": CITY["name"], "city_commune": CITY["commune"]}
        self.parts[passage_id] = [{"part": part, "position": n, "status": passage_store.TO_DO, "step": None,
                                   "started_at": None, "finished_at": None, "summary": None, "error": None}
                                  for n, part in enumerate(parts, start=1)]

    def set_passage_status(self, passage_id, status, error=None):
        self.passages[passage_id].update(status=status, error=error)
        if status == passage_store.RUNNING:
            self.passages[passage_id]["started_at"] = datetime(2026, 11, 19, 10, 5)

    def set_part(self, passage_id, part, status, step=None, summary=None, error=None):
        row = next(row for row in self.parts[passage_id] if row["part"] == part)
        row.update(status=status, step=step, summary=summary, error=error)

    def load_passage(self, passage_id):
        return dict(self.passages[passage_id]) if passage_id in self.passages else None

    def load_parts(self, passage_id):
        return [dict(row) for row in self.parts[passage_id]]

    def load_calls(self, passage_id):
        return self.calls.get(passage_id, [])

    def passage_ids(self, status, limit):
        return [key for key, row in self.passages.items() if row["status"] == status][:limit]

    def resumed_by(self, passage_id):
        return next((key for key, row in self.passages.items() if row["resumed_from"] == passage_id), None)

    def oldest_queued(self):
        # Les passages sont gardés dans l'ordre où ils ont été demandés (un dictionnaire garde l'ordre d'écriture).
        return next((key for key, row in self.passages.items() if row["status"] == passage_store.QUEUED), None)

    def open_parts(self, chain, city_ids):
        return {row["part"] for key, passage in self.passages.items()
                if passage["chain"] == chain and passage["city_id"] in city_ids
                and passage["status"] in ("en_file", "en_attente", "en_cours") for row in self.parts[key]}

    def recent_ids(self, limit):
        return [key for key, row in self.passages.items() if row["status"] in ("fini", "echec")][:limit]


@pytest.fixture
def store(monkeypatch):
    """La trace en mémoire, branchée à la place des requêtes de passage_store."""
    fake = _Store()
    for name in ("insert_passage", "set_passage_status", "set_part", "load_passage", "load_parts", "load_calls",
                 "passage_ids", "recent_ids", "resumed_by", "oldest_queued", "open_parts"):
        monkeypatch.setattr(passage_store, name, getattr(fake, name))
    monkeypatch.setattr(passage_service.service_store, "load_cities", lambda: [CITY])
    monkeypatch.setattr(passage_service.service_store, "load_city", lambda name: CITY)
    # Le budget des agents le permet, sauf si un test pose une raison de blocage dans fake.budget_reason.
    fake.budget_reason = None
    monkeypatch.setattr(passage_service.budget_service, "budget_block", lambda: fake.budget_reason)
    return fake


@pytest.fixture
def chain(monkeypatch):
    """
    La chaîne des services simulée : chaque catégorie note ce qu'on lui demande et le passage en cours, puis rend un
    bilan ; `fail` donne l'erreur à lever pour une catégorie. Le verrou est libre, sauf si `busy` est vrai.
    """
    state = {"ran": [], "fail": {}, "busy": False}

    def run_part(passage_id, key, city, resume):
        state["ran"].append((key, resume, passage_courant()))
        if key in state["fail"]:
            raise state["fail"][key]
        return {"fiches": 3}

    def lock():
        if state["busy"]:
            raise PassageRunning("verrou tenu")
        from contextlib import nullcontext
        return nullcontext()

    fake = passage_service.Chain(key="services", label="Recherche des services", parts=passage_service.SERVICE_LABELS,
                                 paid=True, lock=lock, lock_is_free=lambda: not state["busy"], run_part=run_part,
                                 steps_of=passage_service.service_steps)
    monkeypatch.setitem(passage_service.CHAINS, "services", fake)
    return state


# --- Lancer ---

def test_a_launch_writes_a_queued_passage_with_its_categories_in_chain_order(store, chain):
    """Un passage demandé est « en file », avec les catégories choisies remises dans l'ordre de la chaîne."""
    passage_id = passage_service.create_passage("services", 12, ["laveries", "restaurants"])
    assert store.passages[passage_id]["status"] == "en_file" and store.passages[passage_id]["origin"] == "supervision"
    assert [row["part"] for row in store.parts[passage_id]] == ["restaurants", "laveries"]


def test_a_launch_without_categories_takes_the_whole_chain(store, chain):
    """Sans catégorie choisie, le passage prend toutes celles de la chaîne des services."""
    passage_id = passage_service.create_passage("services", 12)
    assert [row["part"] for row in store.parts[passage_id]] == ["restaurants", "commerces", "supermarches", "laveries"]


@pytest.mark.parametrize("chain_key,city_id,parts,origin", [
    ("pepites", 12, None, "supervision"),
    ("services", 99, None, "supervision"),
    ("services", 12, ["boulangeries"], "supervision"),
    ("services", 12, None, "nuit"),
])
def test_an_unknown_chain_city_category_or_origin_is_refused(store, chain, chain_key, city_id, parts, origin):
    """Une chaîne pas encore branchée, une ville, une catégorie ou une origine inconnue est refusée, sans rien écrire."""
    with pytest.raises(ValueError):
        passage_service.create_passage(chain_key, city_id, parts, origin)
    assert store.passages == {}


def test_a_launch_while_a_passage_runs_names_the_running_one(store, chain):
    """Si un passage tourne déjà, le lancement est refusé avec un message qui nomme sa ville et son heure de début."""
    running = passage_service.create_passage("services", 12)
    store.set_passage_status(running, "en_cours")
    chain["busy"] = True
    with pytest.raises(PassageConflict, match="tourne déjà sur Guidel, depuis le 19/11/2026 à 10 h 05"):
        passage_service.create_passage("services", 12)
    assert len(store.passages) == 1


def test_a_launch_is_refused_when_the_budget_is_reached(store, chain):
    """Quand le budget des agents est atteint, un lancement à la main est refusé avec la raison, et rien n'est écrit."""
    store.budget_reason = "plafond du jour atteint : 10.40 $ dépensés sur 10.00 $"
    with pytest.raises(PassageConflict, match="Budget des agents atteint .plafond du jour atteint"):
        passage_service.create_passage("services", 12)
    assert store.passages == {}


def test_a_lock_held_from_the_command_line_is_named_too(store, chain):
    """Un verrou tenu sans trace vient d'un lancement dans le conteneur : le message le dit."""
    chain["busy"] = True
    with pytest.raises(PassageConflict, match="lancé en ligne de commande"):
        passage_service.create_passage("services", 12)


# --- Faire tourner ---

def test_a_passage_runs_every_category_under_its_own_identifier(store, chain):
    """Toutes les catégories passent, sous l'identifiant du passage : leurs appels d'agents le portent dans llm_calls."""
    passage_id = passage_service.create_passage("services", 12, ["restaurants", "commerces"])
    passage_service.run_passage(passage_id)
    assert chain["ran"] == [("restaurants", False, passage_id), ("commerces", False, passage_id)]
    assert store.passages[passage_id]["status"] == "fini"
    assert [(row["status"], row["summary"]) for row in store.parts[passage_id]] == [("fini", {"fiches": 3})] * 2


def test_a_quota_reached_keeps_the_finished_categories_and_stops(store, chain):
    """Quota de Claude atteint pendant les commerces : les restaurants restent finis, la suite reste à faire, la raison est lisible."""
    chain["fail"]["commerces"] = LLMUnavailable("claude -p : réponse inutilisable (You've hit your session limit · resets 1:40pm (UTC))")
    passage_id = passage_service.create_passage("services", 12, ["restaurants", "commerces", "laveries"])
    passage_service.run_passage(passage_id)
    assert [row["status"] for row in store.parts[passage_id]] == ["fini", "echec", "a_faire"]
    reason = store.passages[passage_id]["error"]
    assert reason.startswith("quota de l'abonnement Claude atteint (il revient à 1:40pm (UTC) : reprendre après cette heure)")
    assert store.parts[passage_id][1]["error"] == reason


def test_a_passage_that_finds_the_lock_taken_keeps_its_place_in_the_queue(store, chain):
    """Un passage qui trouve le verrou pris au moment de partir reste en file, sans échec ni recherche : la file le relancera (#211)."""
    passage_id = passage_service.create_passage("services", 12)
    chain["busy"] = True
    passage_service.run_passage(passage_id)
    assert chain["ran"] == [] and store.passages[passage_id]["status"] == "en_file"
    assert store.passages[passage_id]["error"] is None


def test_a_passage_already_run_is_not_run_twice(store, chain):
    """Si la file et la tâche de fond de la supervision visent le même passage, le second le trouve fini et ne le refait pas."""
    passage_id = passage_service.create_passage("services", 12)
    passage_service.run_passage(passage_id)
    passage_service.run_passage(passage_id)
    assert len(chain["ran"]) == 4 and store.passages[passage_id]["status"] == "fini"


def test_an_etl_request_is_queued_even_while_a_passage_runs_or_the_budget_is_reached(store, chain):
    """Une ville de l'ETL n'est jamais refusée : son passage prend sa place dans la file, verrou pris et budget atteint."""
    chain["busy"] = True
    store.budget_reason = "plafond du jour atteint"
    passage_id = passage_service.create_passage("services", 12, origin="etl")
    assert store.passages[passage_id]["status"] == "en_file" and store.passages[passage_id]["origin"] == "etl"


def test_an_etl_request_waits_for_the_admin_when_the_automatic_update_is_off(store, chain):
    """Mise à jour automatique coupée : le passage de l'ETL est écrit « en attente », pour que l'admin le lance."""
    passage_id = passage_service.create_passage("services", 12, origin="etl", status=passage_store.WAITING)
    assert store.passages[passage_id]["status"] == "en_attente"


# --- Reprendre ---

def test_a_resumed_passage_redoes_only_what_was_not_finished(store, chain):
    """La reprise d'un passage en échec ne refait que les catégories non finies : les restaurants ne sont pas repayés."""
    chain["fail"]["commerces"] = LLMTimeout("trop long")
    failed = passage_service.create_passage("services", 12, ["restaurants", "commerces", "laveries"])
    passage_service.run_passage(failed)
    chain["fail"].clear()
    chain["ran"].clear()
    resumed = passage_service.resume_passage(failed)
    passage_service.run_passage(resumed)
    assert [(key, resume) for key, resume, _ in chain["ran"]] == [("commerces", True), ("laveries", True)]
    assert store.passages[resumed]["resumed_from"] == failed and store.passages[resumed]["status"] == "fini"


def test_a_failed_passage_is_resumed_only_once_and_knows_its_resumption(store, chain):
    """Le passage en échec reste tel quel et nomme sa reprise ; le reprendre une seconde fois est refusé : on reprend la reprise."""
    chain["fail"]["commerces"] = LLMTimeout("trop long")
    failed = passage_service.create_passage("services", 12, ["restaurants", "commerces"])
    passage_service.run_passage(failed)
    resumed = passage_service.resume_passage(failed)
    state = passage_service.read_passage(failed)
    assert (state["etat"], state["repris_par"]) == ("echec", resumed)
    with pytest.raises(PassageConflict, match=f"déjà été repris par {resumed}"):
        passage_service.resume_passage(failed)
    passage_service.run_passage(resumed)
    again = passage_service.resume_passage(resumed)
    assert store.passages[again]["resumed_from"] == resumed


def test_only_a_failed_passage_can_be_resumed(store, chain):
    """Un passage fini ne se relance pas : la relance est refusée avec un message."""
    passage_id = passage_service.create_passage("services", 12)
    passage_service.run_passage(passage_id)
    with pytest.raises(PassageConflict, match="seul un passage en échec ou en attente se relance"):
        passage_service.resume_passage(passage_id)


def test_resuming_an_unknown_passage_gives_nothing(store, chain):
    """La reprise d'un passage qui n'existe pas ne crée rien."""
    assert passage_service.resume_passage("0" * 32) is None and store.passages == {}


# --- Dire où il en est ---

def test_the_state_gives_the_step_and_cost_of_each_category_from_llm_calls(store, chain):
    """L'état d'un passage donne, par catégorie, l'étape lue dans le dernier appel de ses agents et son coût."""
    passage_id = passage_service.create_passage("services", 12, ["restaurants", "laveries"])
    store.set_passage_status(passage_id, "en_cours")
    store.set_part(passage_id, "restaurants", "fini", summary={"fiches": 5})
    store.set_part(passage_id, "laveries", "en_cours")
    store.calls[passage_id] = [
        {"agent": "find_restaurants", "etape": "année 1", "status": "reussi", "cost_usd": 0.5},
        {"agent": "find_laveries", "etape": "année 1", "status": "reussi", "cost_usd": 0.25},
        {"agent": "prove_laveries", "etape": "preuves, lot 2", "status": "delai", "cost_usd": 0.1},
    ]
    chain["busy"] = True        # le passage tient le verrou : il tourne vraiment
    state = passage_service.read_passage(passage_id)
    assert state["ville"] == {"id": 12, "nom": "Guidel", "commune": "Guidel"} and state["origine"] == "supervision"
    assert (state["etat"], state["payant"], state["appels"], state["cout_usd"]) == ("en_cours", True, 3, 0.85)
    restaurants, laveries = state["categories"]
    assert (restaurants["etat"], restaurants["etape"], restaurants["cout_usd"], restaurants["bilan"]) == ("fini", None, 0.5, {"fiches": 5})
    assert (laveries["etape"], laveries["detail_etape"], laveries["agent"]) == ("preuves", "preuves, lot 2", "prove_laveries")
    assert (laveries["appels"], laveries["echecs_appels"], laveries["libelle"]) == (2, 1, "Recherche des laveries")


def test_the_saving_step_is_shown_though_no_agent_announces_it(store, chain):
    """L'enregistrement n'appelle aucun agent : son étape, notée par le code, est montrée telle quelle."""
    passage_id = passage_service.create_passage("services", 12, ["restaurants"])
    store.set_passage_status(passage_id, "en_cours")
    store.set_part(passage_id, "restaurants", "en_cours", step="enregistrement")
    store.calls[passage_id] = [{"agent": "prove_restaurants", "etape": "preuves, lot 1", "status": "reussi", "cost_usd": 0.2}]
    chain["busy"] = True
    part = passage_service.read_passage(passage_id)["categories"][0]
    assert (part["etape"], part["agent"]) == ("enregistrement", None)


def test_a_running_passage_without_its_lock_is_shown_interrupted(store, chain):
    """Un passage « en cours » dont plus personne ne tient le verrou (serveur redémarré) est écrit en échec, à reprendre."""
    passage_id = passage_service.create_passage("services", 12, ["restaurants", "commerces"])
    store.set_passage_status(passage_id, "en_cours")
    store.set_part(passage_id, "restaurants", "en_cours")
    state = passage_service.read_passage(passage_id)
    assert state["etat"] == "echec" and state["raison_echec"].startswith("passage interrompu")
    assert [part["etat"] for part in state["categories"]] == ["echec", "a_faire"]
    assert store.passages[passage_id]["status"] == "echec"


def test_the_list_separates_running_queued_and_recent_passages(store, chain):
    """La liste range les passages en cours, en file et les derniers finis ou en échec."""
    done = passage_service.create_passage("services", 12)
    passage_service.run_passage(done)
    queued = passage_service.create_passage("services", 12)
    listed = passage_service.list_passages()
    assert [p["passage_id"] for p in listed["en_file"]] == [queued]
    assert [p["passage_id"] for p in listed["derniers"]] == [done] and listed["en_cours"] == []


# --- La raison d'un échec ---

@pytest.mark.parametrize("error,reason", [
    (LLMUnavailable("claude -p : réponse inutilisable (You've hit your session limit · resets 7pm (UTC))"),
     "quota de l'abonnement Claude atteint (il revient à 7pm (UTC) : reprendre après cette heure), "
     "les catégories finies ne seront pas repayées"),
    (RuntimeError("Error code: 400 - {'error': {'message': 'Your credit balance is too low to access the Anthropic API.'}}"),
     "crédit de l'API Anthropic épuisé : recharger le compte, puis reprendre"),
    (RuntimeError("Error code: 429 - {'error': {'type': 'rate_limit_error'}}"),
     "trop d'appels à Claude en même temps : reprendre dans quelques minutes"),
    (RuntimeError("Error code: 529 - {'error': {'type': 'overloaded_error'}}"),
     "trop d'appels à Claude en même temps : reprendre dans quelques minutes"),
    (LLMTimeout("claude -p n'a pas répondu en 180 secondes."), "délai dépassé : Claude n'a pas répondu à temps"),
    (ZeroDivisionError("division by zero"), "erreur : division by zero"),
])
def test_a_failure_reason_is_translated_when_known(error, reason):
    """Quota de l'abonnement (message du 9 octobre 2026), crédit de l'API épuisé, API saturée, délai : chacun dit quoi faire ; un cas inconnu garde son message."""
    assert passage_service.failure_reason(error) == reason


# --- La vraie chaîne des services ---

def test_a_service_category_resumes_from_its_stopped_file_and_notes_the_saving_step(monkeypatch):
    """En reprise, une catégorie repart du fichier du passage arrêté, et l'étape « enregistrement » est notée avant d'écrire."""
    seen, steps = {}, []
    monkeypatch.setattr(passage_service, "interrupted_trace", lambda category, city: {"zones": ["finie"]})

    def search_and_save(category, city, stopped=None, before_saving=None):
        seen.update(category=category.key, stopped=stopped)
        before_saving()
        return {"fiches": 2}

    monkeypatch.setattr(passage_service.find_services, "search_and_save", search_and_save)
    monkeypatch.setattr(passage_store, "set_part", lambda passage_id, key, status, step=None: steps.append((key, status, step)))
    summary = passage_service.run_service_category("p1", "laveries", CITY, resume=True)
    assert summary == {"fiches": 2} and seen == {"category": "laveries", "stopped": {"zones": ["finie"]}}
    assert steps == [("laveries", "en_cours", "enregistrement")]


# --- Le bilan en phrase ---

@pytest.mark.parametrize("summary,text", [
    ({"fiches": 3, "sans_page": 0, "a_confirmer": 0, "liquidation": 0, "meme_nom_dans_la_commune": 1},
     "3 services enregistrés ; 1 même nom ailleurs dans la commune, à relire comme doublon possible."),
    ({"fiches": 0, "sans_page": 0, "a_confirmer": 1, "liquidation": 0},
     "Aucun service enregistré ; 1 à confirmer dans la supervision."),
    ({"fiches": 12, "a_confirmer": 2, "sans_page": 2, "liquidation": 1},
     "12 services enregistrés ; 2 à confirmer dans la supervision ; 3 écartés (2 sans preuve, 1 société liquidée ou fermée)."),
    ({"fiches": 1, "nouveau_compteur": 4}, "1 service enregistré ; 4 nouveau_compteur."),
    (None, None),
])
def test_the_summary_of_a_category_is_said_in_one_sentence(summary, text):
    """Le bilan d'une catégorie devient une phrase (supermarchés et laveries de Guidel, 19 novembre 2026) ; une clé inconnue garde son nom."""
    assert passage_service.summary_text(summary) == text


def test_the_state_of_a_category_carries_its_summary_sentence(store, chain):
    """L'état d'une catégorie finie porte la phrase de son bilan, prête pour l'écran ; une catégorie à faire n'en a pas."""
    passage_id = passage_service.create_passage("services", 12, ["supermarches", "laveries"])
    store.set_part(passage_id, "supermarches", "fini", summary={"fiches": 3})
    finished, waiting = passage_service.read_passage(passage_id)["categories"]
    assert finished["bilan_texte"] == "3 services enregistrés." and waiting["bilan_texte"] is None


# --- La file (services/passage_queue.py, issue #211) ---

def test_two_cities_added_one_after_the_other_pass_in_order(store, chain):
    """Deux villes ajoutées coup sur coup par l'ETL passent l'une après l'autre, dans l'ordre d'arrivée : la seconde n'est pas perdue."""
    first = passage_service.create_passage("services", 12, ["restaurants"], origin="etl")
    second = passage_service.create_passage("services", 12, ["laveries"], origin="etl")
    assert passage_queue.run_next() is True
    assert store.passages[first]["status"] == "fini" and store.passages[second]["status"] == "en_file"
    assert passage_queue.run_next() is True
    assert store.passages[second]["status"] == "fini"
    assert [ran[0] for ran in chain["ran"]] == ["restaurants", "laveries"]
    assert passage_queue.run_next() is False


def test_the_queue_waits_while_a_passage_runs(store, chain):
    """Tant qu'un passage tient le verrou, la ville en file attend, avec la raison, et rien n'est cherché."""
    queued = passage_service.create_passage("services", 12, origin="etl")
    chain["busy"] = True
    assert passage_queue.why_waiting(queued) == "attend la fin du passage en cours"
    assert passage_queue.run_next() is False and chain["ran"] == []


def test_the_queue_waits_for_the_budget_then_goes_by_itself(store, chain):
    """Budget atteint : la ville reste en file avec la raison ; dès que le budget le permet, elle part seule."""
    queued = passage_service.create_passage("services", 12, ["restaurants"], origin="etl")
    store.budget_reason = "plafond du jour atteint : 10.40 $ dépensés sur 10.00 $"
    assert passage_queue.run_next() is False
    assert passage_queue.why_waiting(queued).startswith("plafond du jour atteint")
    store.budget_reason = None          # le lendemain, ou le plafond relevé par l'admin
    assert passage_queue.run_next() is True and store.passages[queued]["status"] == "fini"


def test_a_passage_waiting_for_the_admin_is_not_taken_by_the_queue(store, chain):
    """Une ville en attente (mise à jour automatique coupée) n'est pas lancée par la file : elle attend l'admin."""
    passage_service.create_passage("services", 12, origin="etl", status=passage_store.WAITING)
    assert passage_queue.run_next() is False and chain["ran"] == []


def test_an_error_while_reading_the_queue_does_not_stop_the_worker(store, chain, monkeypatch):
    """Une base injoignable un instant est notée dans le journal ; le fil de la file attend le tour suivant au lieu de s'arrêter."""
    turns = []

    def broken():
        turns.append(1)
        raise ConnectionError("base injoignable")

    def stop_after_one_turn(seconds):
        raise SystemExit         # arrête la boucle sans fin du fil, pour le test
    monkeypatch.setattr(passage_queue, "run_next", broken)
    monkeypatch.setattr(passage_queue._wake, "wait", stop_after_one_turn)
    with pytest.raises(SystemExit):
        passage_queue.work_forever()
    assert turns == [1]


# --- La demande de l'ETL d'une nouvelle ville (issue #211) ---

# Le Conquet et Lochrist, un lieu-dit du Conquet (même code INSEE), comme dans cities.
CONQUET = {"id": 30, "name": "Le Conquet", "commune": "Le Conquet", "insee": "29040"}
LOCHRIST = {"id": 31, "name": "Lochrist", "commune": "Le Conquet", "insee": "29040"}


@pytest.fixture
def etl(store, chain, monkeypatch):
    """
    Les villes du Conquet, les fichiers des passages déjà allés au bout (searched : {catégorie : noms des fichiers})
    et le réglage de la mise à jour automatique (activée), tels que l'ETL les trouve.
    """
    state = {"searched": {}, "auto": True}
    cities = [CITY, CONQUET, LOCHRIST]
    monkeypatch.setattr(passage_service.service_store, "load_cities", lambda: cities)
    # load_city rend la ville qui porte le nom de la commune : Lochrist se cherche depuis Le Conquet.
    monkeypatch.setattr(passage_service.service_store, "load_city",
                        lambda name: CONQUET if name in ("Lochrist", "Le Conquet") else CITY)
    monkeypatch.setattr(passage_service, "latest_traces",
                        lambda category: {name: {} for name in state["searched"].get(category.key, ())})
    monkeypatch.setattr(passage_service.budget_service, "load_settings",
                        lambda: {"services_after_etl": state["auto"]})
    return state


def test_the_etl_city_name_becomes_its_official_commune(store, etl):
    """Une rando partie de Lochrist fait chercher la commune officielle, Le Conquet, avec l'origine « etl »."""
    passage_id = passage_service.request_etl_passage("Lochrist")
    passage = store.passages[passage_id]
    assert (passage["city_id"], passage["origin"], passage["status"]) == (CONQUET["id"], "etl", "en_file")
    assert [row["part"] for row in store.parts[passage_id]] == ["restaurants", "commerces", "supermarches", "laveries"]


def test_only_the_categories_never_searched_are_requested(store, etl):
    """Guidel, dont restaurants, supermarchés et laveries sont déjà cherchés : l'ETL ne demande que les commerces."""
    etl["searched"] = {"restaurants": ["Guidel"], "supermarches": ["Guidel"], "laveries": ["Guidel"]}
    passage_id = passage_service.request_etl_passage("Guidel")
    assert [row["part"] for row in store.parts[passage_id]] == ["commerces"]


def test_an_old_file_named_after_the_place_counts_for_its_commune(store, etl):
    """Un fichier d'avant le 8 novembre, au nom de Lochrist, compte pour Le Conquet : rien n'est cherché deux fois."""
    etl["searched"] = {key: ["Lochrist"] for key in passage_service.SERVICE_LABELS}
    assert passage_service.request_etl_passage("Le Conquet") is None
    assert store.passages == {}


def test_a_second_hike_in_the_same_commune_asks_nothing_more(store, etl):
    """Deux randos au Conquet coup sur coup : la seconde ne redemande pas les catégories déjà en file."""
    first = passage_service.request_etl_passage("Le Conquet")
    assert passage_service.request_etl_passage("Lochrist") is None
    assert list(store.passages) == [first]


def test_with_the_automatic_update_off_the_city_waits_for_the_admin(store, etl):
    """Mise à jour automatique coupée : la ville est gardée « en attente », elle n'est pas perdue et la file ne la lance pas."""
    etl["auto"] = False
    passage_id = passage_service.request_etl_passage("Guidel")
    assert store.passages[passage_id]["status"] == "en_attente"
    assert passage_queue.run_next() is False


def test_the_etl_wakes_the_queue_after_its_request(monkeypatch):
    """À la fin de l'ETL, la demande de passage est faite, puis la file est réveillée pour la lancer sans attendre."""
    from etl import etl_pipeline
    calls = []
    monkeypatch.setattr(passage_service, "request_etl_passage", lambda city: calls.append(("demande", city)) or "abc")
    monkeypatch.setattr(passage_queue, "wake", lambda: calls.append(("réveil",)))
    etl_pipeline.launch_services("Guidel")
    assert calls == [("demande", "Guidel"), ("réveil",)]


def test_a_failed_request_does_not_stop_the_etl(monkeypatch):
    """Une base injoignable au moment de la demande est notée dans le journal ; l'ETL de la ville finit quand même."""
    from etl import etl_pipeline

    def broken(city):
        raise ConnectionError("base injoignable")
    monkeypatch.setattr(passage_service, "request_etl_passage", broken)
    etl_pipeline.launch_services("Guidel")


# --- Les villes non faites et leur relance (issue #211) ---

def test_a_city_waiting_for_the_admin_is_launched_by_the_resume_route(store, chain):
    """Une ville en attente (mise à jour coupée) est lancée par la relance : le même passage repart, sans en créer un autre."""
    waiting = passage_service.create_passage("services", 12, ["laveries"], origin="etl", status=passage_store.WAITING)
    assert passage_service.resume_passage(waiting) == waiting
    passage_service.run_passage(waiting)
    assert list(store.passages) == [waiting] and store.passages[waiting]["status"] == "fini"
    assert store.passages[waiting]["origin"] == "etl"


def test_a_waiting_city_is_not_launched_when_the_budget_is_reached(store, chain):
    """Budget atteint : lancer une ville en attente est refusé avec la raison, et elle reste en attente."""
    waiting = passage_service.create_passage("services", 12, origin="etl", status=passage_store.WAITING)
    store.budget_reason = "enveloppe du mois atteinte"
    with pytest.raises(PassageConflict, match="Budget des agents atteint"):
        passage_service.resume_passage(waiting)
    assert store.passages[waiting]["status"] == "en_attente"


def test_the_cities_not_done_are_listed_with_their_reason(store, chain):
    """L'API donne les villes non faites avec leur raison : budget atteint, mise à jour coupée, échec ; un échec repris n'y est plus."""
    store.budget_reason = "plafond du jour atteint : 10.40 $ dépensés sur 10.00 $"
    queued = passage_service.create_passage("services", 12, ["restaurants"], origin="etl")
    waiting = passage_service.create_passage("services", 12, ["commerces"], origin="etl", status=passage_store.WAITING)
    store.budget_reason = None
    chain["fail"]["laveries"] = LLMTimeout("trop long")
    failed = passage_service.create_passage("services", 12, ["laveries"])
    passage_service.run_passage(failed)
    resumed_failure = passage_service.create_passage("services", 12, ["supermarches"])
    chain["fail"]["supermarches"] = LLMTimeout("trop long")
    passage_service.run_passage(resumed_failure)
    store.insert_passage("reprise", "services", 12, "supervision", ["supermarches"], resumed_from=resumed_failure)
    store.budget_reason = "plafond du jour atteint : 10.40 $ dépensés sur 10.00 $"
    rows = {row["passage_id"]: row for row in passage_service.list_passages()["villes_en_attente"]}
    assert rows[queued]["raison"].startswith("plafond du jour atteint") and rows[queued]["origine"] == "etl"
    assert rows[waiting]["raison"] == "mise à jour automatique coupée : à lancer depuis la supervision"
    assert rows[failed]["raison"] == "échec : délai dépassé : Claude n'a pas répondu à temps"
    assert resumed_failure not in rows
