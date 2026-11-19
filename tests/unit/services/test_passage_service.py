"""
Les passages d'une chaîne d'agents lancés depuis la supervision (services/passage_service.py, issue #204).

Aucune base ni aucun agent : la trace des passages est gardée dans un dictionnaire (_Store), et la chaîne des services
est remplacée par une chaîne simulée, qui peut échouer sur la catégorie qu'on lui dit.
"""
from datetime import datetime

import pytest

from agents.find_services import PassageRunning
from agents.llm_service import LLMTimeout, LLMUnavailable, passage_courant
from services import passage_service, passage_store
from services.passage_service import PassageConflict

CITY = {"id": 12, "name": "Guidel", "commune": "Guidel", "insee": "56078"}


class _Store:
    """La trace des passages en mémoire, avec les mêmes fonctions que passage_store, et les appels de llm_calls."""
    def __init__(self):
        self.passages, self.parts, self.calls = {}, {}, {}

    def insert_passage(self, passage_id, chain, city_id, origin, parts, resumed_from=None):
        self.passages[passage_id] = {"passage_id": passage_id, "chain": chain, "city_id": city_id, "origin": origin,
                                     "status": passage_store.QUEUED, "requested_at": datetime(2026, 11, 19, 10),
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

    def recent_ids(self, limit):
        return [key for key, row in self.passages.items() if row["status"] in ("fini", "echec")][:limit]


@pytest.fixture
def store(monkeypatch):
    """La trace en mémoire, branchée à la place des requêtes de passage_store."""
    fake = _Store()
    for name in ("insert_passage", "set_passage_status", "set_part", "load_passage", "load_parts", "load_calls",
                 "passage_ids", "recent_ids", "resumed_by"):
        monkeypatch.setattr(passage_store, name, getattr(fake, name))
    monkeypatch.setattr(passage_service.service_store, "load_cities", lambda: [CITY])
    monkeypatch.setattr(passage_service.service_store, "load_city", lambda name: CITY)
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


def test_a_passage_refused_by_the_lock_fails_with_a_clear_reason(store, chain):
    """Un passage qui trouve le verrou pris au moment de partir échoue, avec la raison, sans rien chercher."""
    passage_id = passage_service.create_passage("services", 12)
    chain["busy"] = True
    passage_service.run_passage(passage_id)
    assert chain["ran"] == [] and store.passages[passage_id]["status"] == "echec"
    assert store.passages[passage_id]["error"] == "un autre passage tournait déjà : relancer après sa fin"


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
    """Un passage fini ne se reprend pas : la reprise est refusée avec un message."""
    passage_id = passage_service.create_passage("services", 12)
    passage_service.run_passage(passage_id)
    with pytest.raises(PassageConflict, match="seul un passage en échec se reprend"):
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
