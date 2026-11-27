"""
Les passages d'une chaîne d'agents lancés depuis la supervision (services/passage_service.py, issue #204).

Aucune base ni aucun agent : la trace des passages est gardée dans un dictionnaire (_Store), et la chaîne des services
est remplacée par une chaîne simulée, qui peut échouer sur la catégorie qu'on lui dit.
"""
from datetime import datetime, timedelta

import pytest

from agents.find_services import PassageRunning
from agents.llm_service import LLMLimitReached, LLMTimeout, LLMUnavailable, passage_courant
from services import agents_pause, passage_queue, passage_service, passage_steps, passage_store
from services.passage_service import PassageConflict

CITY = {"id": 12, "name": "Guidel", "commune": "Guidel", "insee": "56078"}
OTHER = {"id": 13, "name": "Plouarzel", "commune": "Plouarzel", "insee": "29177"}    # une seconde ville, une autre commune
CALLED_AT = datetime(2026, 11, 19, 10, 10)  # le jour des appels de llm_calls, pour convertir leur coût en euros


class _Store:
    """La trace des passages en mémoire, avec les mêmes fonctions que passage_store, et les appels de llm_calls."""
    def __init__(self):
        self.passages, self.parts, self.calls, self.items = {}, {}, {}, []

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

    def queued_next_parts(self):
        # Les passages sont gardés dans l'ordre où ils ont été demandés (un dictionnaire garde l'ordre d'écriture).
        return [{"passage_id": key, "chain": row["chain"], "city_id": row["city_id"],
                 "next_part": next((part["part"] for part in self.parts[key] if part["status"] == passage_store.TO_DO),
                                   None)}
                for key, row in self.passages.items() if row["status"] == passage_store.QUEUED]

    def pending_part(self, chain, part, city_ids, other_than):
        # Comme la requête : la partie pas finie dans un autre passage ouvert, ou en échec pas encore repris.
        def still_open(key, passage):
            return (passage["status"] in ("en_file", "en_attente", "en_cours")
                    or (passage["status"] == "echec" and self.resumed_by(key) is None))
        return any(row["part"] == part and row["status"] != "fini"
                   for key, passage in self.passages.items()
                   if passage["chain"] == chain and passage["city_id"] in city_ids and key != other_than
                   and still_open(key, passage)
                   for row in self.parts[key])

    def failures_to_resume(self, chains, since):
        # Comme la requête : les échecs de l'ETL sur ces chaînes, finis depuis `since`, que personne n'a repris.
        return [{"passage_id": key, "chain": row["chain"], "city_id": row["city_id"],
                 "resumed_from": row["resumed_from"], "finished_at": row["finished_at"]}
                for key, row in self.passages.items()
                if row["status"] == passage_store.FAILED and row["origin"] == "etl" and row["chain"] in chains
                and row["finished_at"] and row["finished_at"] >= since and self.resumed_by(key) is None]

    def active_ids(self, chain, city_id):
        # Comme la requête : les passages de la chaîne sur la ville, en file, en attente ou en cours.
        return [key for key, row in self.passages.items() if row["chain"] == chain and row["city_id"] == city_id
                and row["status"] in ("en_file", "en_attente", "en_cours")]

    def running_ids(self, chain):
        return [key for key, row in self.passages.items()
                if row["status"] == passage_store.RUNNING and row["chain"] == chain]

    def open_parts(self, chain, city_ids):
        # Comme la requête : un passage en file, en attente ou en cours, ou un échec pas encore repris.
        def still_open(key, passage):
            return (passage["status"] in ("en_file", "en_attente", "en_cours")
                    or (passage["status"] == "echec" and self.resumed_by(key) is None))
        return {row["part"] for key, passage in self.passages.items()
                if passage["chain"] == chain and passage["city_id"] in city_ids and still_open(key, passage)
                for row in self.parts[key]}

    def finished_parts(self, chain, city_ids):
        # Comme la requête : les parties finies, dans n'importe quel passage de ces villes.
        return {row["part"] for key, passage in self.passages.items()
                if passage["chain"] == chain and passage["city_id"] in city_ids
                for row in self.parts[key] if row["status"] == "fini"}

    def load_items(self, passage_id, item_type=None, item_id=None):
        # Comme la requête : le journal du passage, réduit à un objet si on le donne.
        return [row for row in self.items if row["passage_id"] == passage_id
                and (item_type is None or (row["item_type"], row["item_id"]) == (item_type, item_id))]

    def count_items(self, passage_id):
        return len(self.load_items(passage_id))

    def passages_of_item(self, item_type, item_id):
        # Du plus récent au plus ancien : le journal est gardé dans l'ordre d'écriture.
        ids = [row["passage_id"] for row in reversed(self.items) if (row["item_type"], row["item_id"]) == (item_type, item_id)]
        return list(dict.fromkeys(ids))

    def recent_ids(self, limit):
        return [key for key, row in self.passages.items() if row["status"] in ("fini", "echec")][:limit]


@pytest.fixture
def store(monkeypatch):
    """La trace en mémoire, branchée à la place des requêtes de passage_store."""
    fake = _Store()
    for name in ("insert_passage", "set_passage_status", "set_part", "load_passage", "load_parts", "load_calls",
                 "passage_ids", "recent_ids", "resumed_by", "queued_next_parts", "pending_part", "running_ids", "active_ids", "open_parts", "finished_parts",
                 "failures_to_resume",
                 "load_items", "count_items", "passages_of_item"):
        monkeypatch.setattr(passage_store, name, getattr(fake, name))
    monkeypatch.setattr(passage_service.service_store, "load_cities", lambda: [CITY, OTHER])
    monkeypatch.setattr(passage_service.service_store, "load_city", lambda name: CITY)
    # Le budget des agents le permet, sauf si un test pose une raison de blocage dans fake.budget_reason.
    fake.budget_reason = None
    monkeypatch.setattr(passage_service.budget_service, "budget_block", lambda: fake.budget_reason)
    # Aucune pause des agents laissée par un test précédent : elle est gardée en mémoire, dans le module.
    agents_pause.clear()
    yield fake
    agents_pause.clear()


def run_next() -> bool:
    """Fait partir un passage prêt, en essayant les étapes de la file l'une après l'autre ; False si aucune n'en a."""
    return any(passage_queue.run_step_once(step) for step in passage_steps.STEPS)


@pytest.fixture
def chain(monkeypatch):
    """
    La chaîne des services simulée : chaque catégorie note ce qu'on lui demande et le passage en cours, puis rend un
    bilan ; `fail` donne l'erreur à lever pour une catégorie. Le verrou est libre, sauf si `busy` est vrai.
    """
    state = {"ran": [], "fail": {}, "busy": False, "zone_budget": set()}

    def run_part(passage_id, key, city, resume, check_budget):
        state["ran"].append((key, resume, passage_courant()))
        if key in state["zone_budget"]:
            check_budget()      # une grande ville regarde le budget avant sa zone suivante
        if key in state["fail"]:
            raise state["fail"][key]
        return {"fiches": 3}

    def lock(city_id, part):
        if state["busy"]:
            raise PassageRunning("verrou tenu")
        from contextlib import nullcontext
        return nullcontext()

    fake = passage_service.Chain(key="services", label="Recherche des services", parts=passage_service.SERVICE_LABELS,
                                 paid=True, lock=lock, lock_is_free=lambda city_id, part: not state["busy"], run_part=run_part,
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
    ("chaine_future", 12, None, "supervision"),
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


def test_a_launch_while_the_chain_runs_on_another_city_enters_the_queue(store, chain):
    """Les services tournent sur une autre ville : le lancement n'est plus refusé, le passage entre dans la file (#332)."""
    store.insert_passage("ailleurs", "services", 99, "etl", ["restaurants"])
    store.set_passage_status("ailleurs", "en_cours")
    chain["busy"] = True
    passage_id = passage_service.create_passage("services", 12)
    assert store.passages[passage_id]["status"] == "en_file"


def test_a_launch_while_the_chain_is_queued_on_the_city_names_it(store, chain):
    """La même chaîne déjà en file sur la ville : le lancement est refusé, le message nomme le passage qui partira."""
    queued = passage_service.create_passage("services", 12, origin="etl")
    with pytest.raises(PassageConflict, match=f"déjà demandé sur Guidel .{queued}, en_file"):
        passage_service.create_passage("services", 12)


def test_a_launch_refused_does_not_name_a_passage_of_another_chain(store, chain):
    """Un passage d'une autre chaîne en cours sur la ville ne retient pas le lancement des services."""
    store.insert_passage("autre", "carburants", 12, "etl", ["carburants"])
    store.set_passage_status("autre", "en_cours")
    passage_id = passage_service.create_passage("services", 12)
    assert store.passages[passage_id]["status"] == "en_file"


# --- Faire tourner ---

def test_a_passage_runs_every_category_under_its_own_identifier(store, chain):
    """Toutes les catégories passent, sous l'identifiant du passage : leurs appels d'agents le portent dans llm_calls."""
    passage_id = passage_service.create_passage("services", 12, ["restaurants", "commerces"])
    passage_service.run_passage(passage_id)
    assert chain["ran"] == [("restaurants", False, passage_id), ("commerces", False, passage_id)]
    assert store.passages[passage_id]["status"] == "fini"
    assert [(row["status"], row["summary"]) for row in store.parts[passage_id]] == [("fini", {"fiches": 3})] * 2


def quota() -> LLMLimitReached:
    """
    La limite que lève le service d'accès au modèle quand le quota des agents est atteint, pour l'heure qui vient.
    L'heure de retour part de maintenant : une heure fixe (13 h 42 le 27 novembre) faisait échouer ces tests une fois
    l'heure passée.
    """
    return LLMLimitReached("session limit", datetime.now() + timedelta(hours=1), "quota des agents atteint")


def test_a_quota_reached_puts_the_passage_back_in_the_queue_without_failure(store, chain):
    """Quota des agents atteint pendant les commerces : pas d'échec, les restaurants restent finis, le passage attend en file (27 novembre 2026, villes 507 à 538)."""
    chain["fail"]["commerces"] = quota()
    passage_id = passage_service.create_passage("services", 12, ["restaurants", "commerces", "laveries"])
    passage_service.run_passage(passage_id)
    assert store.passages[passage_id]["status"] == "en_file" and store.passages[passage_id]["error"] is None
    assert [(row["status"], row["step"]) for row in store.parts[passage_id]] == [
        ("fini", None), ("a_faire", "budget"), ("a_faire", None)]
    assert passage_queue.why_waiting(passage_id).startswith("quota des agents atteint : la file reprend seule vers")


def test_after_the_quota_the_passage_resumes_alone_without_paying_again(store, chain):
    """L'heure de retour des agents passée, l'étape des services reprend seule les commerces sur leur fichier, sans refaire les restaurants."""
    chain["fail"]["commerces"] = quota()
    passage_id = passage_service.create_passage("services", 12, ["restaurants", "commerces"])
    passage_service.run_passage(passage_id)
    assert run_next() is False                  # la pause des agents retient l'étape payante
    agents_pause.clear()                        # l'heure de retour est passée
    del chain["fail"]["commerces"]
    assert run_next() is True
    assert [ran[0] for ran in chain["ran"]] == ["restaurants", "commerces", "commerces"]
    assert chain["ran"][-1] == ("commerces", True, passage_id)
    assert store.passages[passage_id]["status"] == "fini"


def test_an_empty_api_credit_stays_a_failure(store, chain):
    """Le crédit de l'API épuisé ne revient pas seul : la partie passe en échec, avec la raison, pour l'administratrice."""
    chain["fail"]["restaurants"] = LLMUnavailable("Error code: 400 - Your credit balance is too low")
    passage_id = passage_service.create_passage("services", 12, ["restaurants"])
    passage_service.run_passage(passage_id)
    assert store.passages[passage_id]["status"] == "echec"
    assert store.passages[passage_id]["error"].startswith("crédit de l'API Anthropic épuisé")


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


def test_a_resume_is_accepted_while_the_same_step_runs_on_another_city(store, chain):
    """Reprendre les services de Guidel pendant qu'ils tournent sur une autre ville : accepté, la reprise entre dans la file (Bedous et Rocquefort, #332)."""
    chain["fail"]["laveries"] = LLMTimeout("trop long")
    failed = passage_service.create_passage("services", 12, ["laveries"], origin="etl")
    passage_service.run_passage(failed)
    store.insert_passage("ailleurs", "services", 13, "etl", ["restaurants"])
    store.set_passage_status("ailleurs", "en_cours")
    chain["busy"] = True
    resumed = passage_service.resume_passage(failed)
    assert store.passages[resumed]["status"] == "en_file" and store.passages[resumed]["resumed_from"] == failed
    assert passage_queue.why_waiting(resumed) == "attend la fin du passage en cours"


def test_a_waiting_city_is_launched_while_the_same_step_runs_on_another_city(store, chain):
    """Lancer une ville en attente pendant que la même étape tourne ailleurs : elle retourne en file, sans refus (#332)."""
    waiting = passage_service.create_passage("services", 12, origin="etl", status=passage_store.WAITING)
    chain["busy"] = True
    assert passage_service.resume_passage(waiting) == waiting and store.passages[waiting]["status"] == "en_file"


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
        {"agent": "find_restaurants", "etape": "année 1", "status": "reussi", "cost_usd": 0.5, "called_at": CALLED_AT, "engine": "claude-code"},
        {"agent": "find_laveries", "etape": "année 1", "status": "reussi", "cost_usd": 0.25, "called_at": CALLED_AT, "engine": "claude-code"},
        {"agent": "prove_laveries", "etape": "preuves, lot 2", "status": "delai", "cost_usd": 0.1, "called_at": CALLED_AT, "engine": "claude-code"},
    ]
    chain["busy"] = True        # le passage tient le verrou : il tourne vraiment
    state = passage_service.read_passage(passage_id)
    assert state["ville"] == {"id": 12, "nom": "Guidel", "commune": "Guidel"} and state["origine"] == "supervision"
    assert (state["etat"], state["payant"], state["appels"], state["cout_usd"]) == ("en_cours", True, 3, 0.85)
    # Le taux des tests (1,20 $ pour un euro) compense la TVA : 0,85 $ font 0,85 € TTC, en équivalent API.
    assert (state["cout_eur"], state["nature_du_cout"]) == (0.85, "équivalent API, abonnement")
    assert state["taux"] == "taux BCE du 19/11/2026 : 1 € = 1.2000 $"
    restaurants, laveries = state["categories"]
    assert (restaurants["etat"], restaurants["etape"], restaurants["cout_usd"], restaurants["bilan"]) == ("fini", None, 0.5, {"fiches": 5})
    assert (laveries["etape"], laveries["detail_etape"], laveries["agent"]) == ("preuves", "preuves, lot 2", "prove_laveries")
    assert (laveries["appels"], laveries["echecs_appels"], laveries["libelle"]) == (2, 1, "Recherche des laveries")


def test_the_saving_step_is_shown_though_no_agent_announces_it(store, chain):
    """L'enregistrement n'appelle aucun agent : son étape, notée par le code, est montrée telle quelle."""
    passage_id = passage_service.create_passage("services", 12, ["restaurants"])
    store.set_passage_status(passage_id, "en_cours")
    store.set_part(passage_id, "restaurants", "en_cours", step="enregistrement")
    store.calls[passage_id] = [{"agent": "prove_restaurants", "etape": "preuves, lot 1", "status": "reussi", "cost_usd": 0.2, "called_at": CALLED_AT, "engine": "claude-code"}]
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

    def search_and_save(category, city, stopped=None, before_saving=None, check_budget=None):
        seen.update(category=category.key, stopped=stopped)
        before_saving()
        return {"fiches": 2}

    monkeypatch.setattr(passage_service.find_services, "search_and_save", search_and_save)
    monkeypatch.setattr(passage_store, "set_part", lambda passage_id, key, status, step=None: steps.append((key, status, step)))
    summary = passage_service.run_service_category("p1", "laveries", CITY, resume=True, check_budget=lambda: None)
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


# --- La file (services/passage_queue.py, issues #211 et #332) ---

def test_two_cities_added_one_after_the_other_pass_in_order(store, chain):
    """Deux villes ajoutées coup sur coup par l'ETL passent l'une après l'autre, dans l'ordre d'arrivée : la seconde n'est pas perdue."""
    first = passage_service.create_passage("services", 12, ["restaurants"], origin="etl")
    second = passage_service.create_passage("services", 12, ["laveries"], origin="etl")
    assert run_next() is True
    assert store.passages[first]["status"] == "fini" and store.passages[second]["status"] == "en_file"
    assert run_next() is True
    assert store.passages[second]["status"] == "fini"
    assert [ran[0] for ran in chain["ran"]] == ["restaurants", "laveries"]
    assert run_next() is False


def test_the_queue_waits_while_a_passage_runs(store, chain):
    """Tant qu'un passage tient le verrou, la ville en file attend, avec la raison, et rien n'est cherché."""
    queued = passage_service.create_passage("services", 12, origin="etl")
    chain["busy"] = True
    assert passage_queue.why_waiting(queued) == "attend la fin du passage en cours"
    assert run_next() is False and chain["ran"] == []


def test_the_queue_waits_for_the_budget_then_goes_by_itself(store, chain):
    """Budget atteint : la ville reste en file avec la raison ; dès que le budget le permet, elle part seule."""
    queued = passage_service.create_passage("services", 12, ["restaurants"], origin="etl")
    store.budget_reason = "plafond du jour atteint : 10.40 $ dépensés sur 10.00 $"
    assert run_next() is False
    assert passage_queue.why_waiting(queued).startswith("plafond du jour atteint")
    store.budget_reason = None          # le lendemain, ou le plafond relevé par l'admin
    assert run_next() is True and store.passages[queued]["status"] == "fini"


def test_a_free_step_does_not_wait_behind_a_paid_step_held_by_the_budget(store, chain, free):
    """OSM d'une ville part même si les services, demandés plus tôt, attendent le budget du lendemain."""
    held = passage_service.create_passage("services", 12, ["restaurants"], origin="etl")
    osm = passage_service.create_passage("osm", 13, origin="etl")
    store.budget_reason = "plafond du jour atteint : 10.40 $ dépensés sur 10.00 $"
    assert run_next() is True
    assert store.passages[osm]["status"] == "fini"
    assert store.passages[held]["status"] == "en_file" and chain["ran"] == []


def chain_lock_free(city_id, part):
    """Un verrou toujours libre, pour une chaîne simulée."""
    from contextlib import nullcontext
    return nullcontext()


def step(key):
    """L'étape de la file de cette clé (services/passage_steps.py)."""
    return passage_steps.STEPS_BY_KEY[key]


@pytest.mark.parametrize("chain_key,part,step_key", [
    ("osm", "osm", "osm"), ("carburants", "carburants", "carburants"), ("finess", "finess", "finess"),
    ("pepites", "lieux", "pepites"), ("services", "laveries", "services"),
    ("spots", "source", "source"), ("spots", "harmonisation", "agents_spots"), ("spots", "verification", "agents_spots"),
])
def test_each_part_belongs_to_the_file_of_its_step(chain_key, part, step_key):
    """Chaque partie va dans la file de son étape : la source des spots et ses agents sont deux étapes (#332)."""
    assert passage_steps.step_for(chain_key, part) is step(step_key)


def test_the_services_of_a_city_wait_for_its_osm_not_for_the_osm_of_the_others(store, chain, free):
    """Les services de la ville 12 attendent son OSM, puis partent alors que l'OSM de la ville 13 est encore en file (#332)."""
    services = passage_service.create_passage("services", 12, ["restaurants"], origin="etl")
    osm_12 = passage_service.create_passage("osm", 12, origin="etl")
    passage_service.create_passage("osm", 13, origin="etl")
    assert passage_queue.next_for(step("services")) is None
    assert passage_queue.why_waiting(services) == "attend OSM et Wikidata de la ville"
    assert passage_queue.run_step_once(step("osm")) is True and store.passages[osm_12]["status"] == "fini"
    assert passage_queue.next_for(step("services")) == services


def test_the_osm_step_chains_the_cities_while_the_services_of_the_first_wait(store, chain, free):
    """OSM enchaîne les villes, une à la fois, sans attendre les services de la première : ils sont dans une autre file (#332)."""
    passage_service.create_passage("osm", 12, origin="etl")
    passage_service.create_passage("services", 12, ["restaurants"], origin="etl")
    passage_service.create_passage("osm", 13, origin="etl")
    store.budget_reason = "plafond du jour atteint"
    assert passage_queue.run_step_once(step("osm")) is True
    assert passage_queue.run_step_once(step("osm")) is True
    assert free["asked"] == [("osm", "Guidel"), ("osm", "Guidel")] and chain["ran"] == []


def test_a_city_with_a_failed_osm_only_holds_its_own_services(store, chain, free):
    """OSM de la ville 12 en échec : ses services attendent, ceux de la ville 13, dont l'OSM est fini, partent (#332)."""
    free["loaded"]["osm"] = None
    failed = passage_service.create_passage("osm", 12, origin="etl")
    passage_service.run_passage(failed)
    held = passage_service.create_passage("services", 12, ["restaurants"], origin="etl")
    free["loaded"]["osm"] = 40
    passage_service.run_passage(passage_service.create_passage("osm", 13, origin="etl"))
    other = passage_service.create_passage("services", 13, ["restaurants"], origin="etl")
    assert passage_queue.next_for(step("services")) == other
    assert passage_queue.why_waiting(held) == "attend OSM et Wikidata de la ville"


def test_a_city_without_any_osm_asked_is_ready_for_its_services(store, chain):
    """Une ville ajoutée avant les passages n'a aucun OSM demandé : ses services ne l'attendent pas, rien ne viendrait."""
    services = passage_service.create_passage("services", 12, ["restaurants"], origin="etl")
    assert passage_queue.next_for(step("services")) == services


def test_a_chain_unknown_to_the_queue_is_never_taken(store, chain):
    """Une chaîne qu'aucune étape ne connaît (écrite par une autre version du code) n'est prise par aucune file, sans les bloquer."""
    store.insert_passage("inconnu", "chaine_future", 12, "etl", ["partie"])
    services = passage_service.create_passage("services", 12, ["restaurants"], origin="etl")
    assert run_next() is True and store.passages[services]["status"] == "fini"
    assert store.passages["inconnu"]["status"] == "en_file"


def test_a_passage_waiting_for_the_admin_is_not_taken_by_the_queue(store, chain):
    """Une ville en attente (mise à jour automatique coupée) n'est pas lancée par la file : elle attend l'admin."""
    passage_service.create_passage("services", 12, origin="etl", status=passage_store.WAITING)
    assert run_next() is False and chain["ran"] == []


def test_an_error_while_reading_the_queue_does_not_stop_the_worker(store, chain, monkeypatch):
    """Une base injoignable un instant est notée dans le journal ; le fil d'une étape attend le tour suivant au lieu de s'arrêter."""
    turns = []

    def broken(step):
        turns.append(step.key)
        raise ConnectionError("base injoignable")

    def stop_after_one_turn(seconds):
        raise SystemExit         # arrête la boucle sans fin du fil, pour le test
    monkeypatch.setattr(passage_queue, "run_step_once", broken)
    monkeypatch.setattr(passage_queue._wakes["osm"], "wait", stop_after_one_turn)
    with pytest.raises(SystemExit):
        passage_queue.work_on_step(step("osm"))
    assert turns == ["osm"]


def test_a_finished_city_wakes_the_other_steps(store, chain, free, monkeypatch):
    """OSM d'une ville fini : les autres étapes sont réveillées tout de suite, sans attendre leur minute (#332)."""
    woken = []
    monkeypatch.setattr(passage_queue, "wake", lambda: woken.append(True))
    passage_service.create_passage("osm", 12, origin="etl")
    assert passage_queue.run_step_once(step("osm")) is True and woken == [True]


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


def test_a_category_finished_in_the_shared_base_is_not_asked_again(store, etl):
    """Guidel, dont supermarchés et laveries sont finis dans la base sans fichier visible (fait depuis une autre branche) : l'ETL ne les redemande pas."""
    store.insert_passage("ancien", "services", CITY["id"], "supervision", ["supermarches", "laveries"])
    passage_store.set_part("ancien", "supermarches", "fini")
    passage_store.set_part("ancien", "laveries", "fini")
    etl["searched"] = {"restaurants": ["Guidel"]}
    passage_id = passage_service.request_etl_passage("Guidel")
    assert [row["part"] for row in store.parts[passage_id]] == ["commerces"]


def test_a_category_finished_before_a_failure_stays_done(store, etl):
    """Une catégorie finie avant la coupure (restaurants) et celle finie par la reprise (commerces) comptent : seules les autres sont demandées."""
    store.insert_passage("coupe", "services", CONQUET["id"], "etl", ["restaurants", "commerces"])
    passage_store.set_part("coupe", "restaurants", "fini")
    passage_store.set_passage_status("coupe", "echec", "quota de l'abonnement Claude atteint")
    store.insert_passage("reprise", "services", CONQUET["id"], "supervision", ["commerces"], resumed_from="coupe")
    passage_store.set_part("reprise", "commerces", "fini")
    passage_store.set_passage_status("reprise", "fini")
    passage_id = passage_service.request_etl_passage("Lochrist")
    assert [row["part"] for row in store.parts[passage_id]] == ["supermarches", "laveries"]


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


def test_a_second_hike_does_not_ask_again_a_city_whose_failure_waits_for_its_resume(store, etl):
    """Un échec pas encore repris garde ses catégories : une seconde rando n'en redemande pas (Paimpont, 19 novembre 2026), sa reprise les refera."""
    failed = passage_service.request_etl_passage("Le Conquet")
    passage_store.set_passage_status(failed, "echec", "quota de l'abonnement Claude atteint")
    assert passage_service.request_etl_passage("Lochrist") is None
    assert list(store.passages) == [failed]


def test_once_the_failure_is_resumed_its_categories_no_longer_block(store, etl):
    """Un échec déjà repris ne compte plus : seule sa reprise dit ce qui est demandé."""
    failed = passage_service.request_etl_passage("Le Conquet")
    passage_store.set_passage_status(failed, "echec", "quota de l'abonnement Claude atteint")
    store.insert_passage("reprise", "services", CONQUET["id"], "supervision", ["laveries"], resumed_from=failed)
    passage_store.set_passage_status("reprise", "fini")
    assert passage_service.request_etl_passage("Lochrist") is not None


def test_with_the_automatic_update_off_the_city_waits_for_the_admin(store, etl):
    """Mise à jour automatique coupée : la ville est gardée « en attente », elle n'est pas perdue et la file ne la lance pas."""
    etl["auto"] = False
    passage_id = passage_service.request_etl_passage("Guidel")
    assert store.passages[passage_id]["status"] == "en_attente"
    assert run_next() is False


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
    failed = passage_service.create_passage("services", 12, ["laveries"], origin="etl")
    passage_service.run_passage(failed)
    resumed_failure = passage_service.create_passage("services", 12, ["supermarches"], origin="etl")
    chain["fail"]["supermarches"] = LLMTimeout("trop long")
    passage_service.run_passage(resumed_failure)
    store.insert_passage("reprise", "services", 12, "supervision", ["supermarches"], resumed_from=resumed_failure)
    store.budget_reason = "plafond du jour atteint : 10.40 $ dépensés sur 10.00 $"
    rows = {row["passage_id"]: row for row in passage_service.list_passages()["villes_en_attente"]}
    assert rows[queued]["raison"].startswith("plafond du jour atteint") and rows[queued]["origine"] == "etl"
    assert rows[waiting]["raison"] == "mise à jour automatique coupée : à lancer depuis la supervision"
    assert rows[failed]["raison"] == "échec : délai dépassé : Claude n'a pas répondu à temps"
    assert resumed_failure not in rows


# --- Le budget regardé pendant le passage (issue #211, essai de Rennes) ---

def test_a_passage_stops_between_two_categories_when_the_budget_is_reached(store, chain, monkeypatch):
    """Budget atteint après les restaurants : le passage retourne en file, les restaurants restent faits, les commerces attendent."""
    passage_id = passage_service.create_passage("services", 12, ["restaurants", "commerces"], origin="etl")
    calls = iter([None, "plafond du jour atteint"])      # libre avant les restaurants, atteint avant les commerces
    monkeypatch.setattr(passage_service.budget_service, "budget_block", lambda: next(calls))
    passage_service.run_passage(passage_id)
    assert store.passages[passage_id]["status"] == "en_file"
    assert [(row["part"], row["status"], row["step"]) for row in store.parts[passage_id]] == [
        ("restaurants", "fini", None), ("commerces", "a_faire", "budget")]
    assert [ran[0] for ran in chain["ran"]] == ["restaurants"]


def test_a_big_city_stopped_between_two_zones_resumes_its_file_when_the_budget_returns(store, chain, monkeypatch):
    """Rennes arrêtée entre deux zones : elle retourne en file sans échec, puis reprend son fichier, sans repayer ses zones finies."""
    passage_id = passage_service.create_passage("services", 12, ["restaurants"], origin="etl")
    chain["zone_budget"] = {"restaurants"}
    budget = iter([None, "plafond du jour atteint"])     # libre au départ, atteint avant la zone suivante
    monkeypatch.setattr(passage_service.budget_service, "budget_block", lambda: next(budget, None))
    passage_service.run_passage(passage_id)
    assert store.passages[passage_id]["status"] == "en_file" and store.passages[passage_id]["error"] is None
    chain["zone_budget"] = set()
    assert run_next() is True
    assert store.passages[passage_id]["status"] == "fini"
    assert [(key, resume) for key, resume, _ in chain["ran"]] == [("restaurants", False), ("restaurants", True)]


# --- Les chaînes gratuites de l'ajout d'une ville : OSM, FINESS, carburants (issue #276) ---

@pytest.fixture
def free(monkeypatch):
    """
    Les chaînes OSM et carburants, avec leurs vraies règles, mais sans réseau ni base : l'étape de l'ETL rend ce qu'on
    lui donne dans `loaded` (None : échec), et le verrou de chaque ville est libre, sauf celles de `busy`.
    """
    state = {"loaded": {"osm": 42, "carburants": 3}, "asked": [], "busy": set()}

    def etl_step(key):
        def run(city_name):
            state["asked"].append((key, city_name))
            return state["loaded"][key]
        return run

    def lock(key, city_id):
        if (key, city_id) in state["busy"]:
            raise PassageRunning("verrou tenu")
        from contextlib import nullcontext
        return nullcontext()

    monkeypatch.setattr(passage_service.etl_chains, "run_osm_etl", etl_step("osm"))
    monkeypatch.setattr(passage_service.etl_chains, "run_fuel_etl", etl_step("carburants"))
    monkeypatch.setattr(passage_service.etl_chains, "city_lock", lock)
    monkeypatch.setattr(passage_service.etl_chains, "city_lock_is_free",
                        lambda key, city_id: (key, city_id) not in state["busy"])
    return state


def test_osm_is_launched_on_a_city_like_any_chain(store, free):
    """La route de lancement relance OSM pour une ville : le passage passe, avec ce qu'il a chargé en bilan lisible."""
    passage_id = passage_service.create_passage("osm", 12)
    passage_service.run_passage(passage_id)
    passage = passage_service.read_passage(passage_id)
    assert passage["etat"] == "fini" and passage["payant"] is False
    assert passage["categories"][0]["bilan_texte"] == "42 lieux chargés."
    assert free["asked"] == [("osm", "Guidel")]


def test_a_free_chain_loads_the_city_itself_not_its_commune(store, free, monkeypatch):
    """OSM de Morgat se charge sur Morgat : seule la chaîne des services cherche depuis la ville de la commune (Crozon)."""
    morgat = {"id": 13, "name": "Morgat", "commune": "Crozon", "insee": "29042"}
    monkeypatch.setattr(passage_service.service_store, "load_cities", lambda: [CITY, morgat])
    passage_id = passage_service.create_passage("osm", 13)
    store.passages[passage_id]["city_name"] = "Morgat"
    passage_service.run_passage(passage_id)
    assert free["asked"] == [("osm", "Morgat")]


def test_an_osm_failure_is_kept_with_its_reason_and_resumed_without_a_script(store, free):
    """Saint-Philibert sans réponse d'OSM : l'échec est gardé avec sa raison, puis la reprise le recharge, sans script."""
    free["loaded"]["osm"] = None
    failed = passage_service.create_passage("osm", 12, origin="etl")
    passage_service.run_passage(failed)
    passage = passage_service.read_passage(failed)
    assert passage["etat"] == "echec" and passage["raison_echec"].startswith("OpenStreetMap n'a pas répondu")
    assert passage["categories"][0]["raison_echec"] == passage["raison_echec"]
    assert passage_service.list_passages()["villes_en_attente"][0]["passage_id"] == failed
    free["loaded"]["osm"] = 40
    resumed = passage_service.resume_passage(failed)
    passage_service.run_passage(resumed)
    assert store.passages[resumed]["status"] == "fini" and store.passages[resumed]["resumed_from"] == failed


def test_a_free_chain_is_never_held_by_the_budget(store, free):
    """Budget des agents atteint : OSM et les carburants se lancent quand même, ils ne coûtent rien."""
    store.budget_reason = "plafond du jour atteint : 10.40 $ dépensés sur 10.00 $"
    passage_id = passage_service.create_passage("carburants", 12)
    passage_service.run_passage(passage_id)
    assert store.passages[passage_id]["status"] == "fini"


def test_a_free_chain_is_refused_only_on_the_same_city(store, free):
    """OSM qui tourne sur Guidel refuse un second OSM sur Guidel, en le nommant, mais pas OSM sur une autre ville."""
    running = passage_service.create_passage("osm", 12)
    store.set_passage_status(running, "en_cours")
    free["busy"].add(("osm", 12))
    with pytest.raises(PassageConflict, match="« Lieux d'OpenStreetMap » tourne déjà sur Guidel"):
        passage_service.create_passage("osm", 12)
    assert passage_service.create_passage("osm", 13)        # Plouarzel : rien ne la retient


def test_a_running_free_chain_shows_the_loading_step(store, free):
    """Une partie d'OSM en cours montre l'étape « chargement » : elle n'a aucun agent dont lire l'étape."""
    passage_id = passage_service.create_passage("osm", 12)
    store.set_passage_status(passage_id, "en_cours")
    store.set_part(passage_id, "osm", "en_cours")
    free["busy"].add(("osm", 12))       # le verrou est tenu : le passage tourne vraiment
    assert passage_service.read_passage(passage_id)["categories"][0]["etape"] == "chargement"


# --- Une chaîne inconnue de cette version du code (base commune aux branches, issue #276) ---

def _unknown_passage(store, status):
    """Un passage d'une chaîne écrite par une version plus récente du code, que celle-ci ne connaît pas."""
    store.insert_passage("inconnu", "chaine_future", 12, "etl", ["harmonisation"])
    store.set_passage_status("inconnu", status)
    return "inconnu"


def test_a_passage_of_an_unknown_chain_is_shown_without_crashing_the_list(store, chain):
    """Un passage d'une chaîne qu'une branche en retard ne connaît pas se lit tel quel : la liste des passages ne plante pas."""
    _unknown_passage(store, "en_cours")
    listed = passage_service.list_passages()
    running = listed["en_cours"][0]
    assert running["chaine"] == "chaine_future" and running["categories"][0]["libelle"] == "harmonisation"
    # Il tourne peut-être sous une autre version : il n'est pas marqué interrompu ici.
    assert store.passages["inconnu"]["status"] == "en_cours"


def test_a_queued_passage_of_an_unknown_chain_is_never_run_here(store, chain):
    """La file laisse de côté un passage d'une chaîne inconnue, avec la raison, et fait partir ceux d'après."""
    _unknown_passage(store, "en_file")
    known = passage_service.create_passage("services", 12, ["restaurants"], origin="etl")
    assert passage_queue.why_waiting("inconnu") == passage_service.UNKNOWN_CHAIN
    assert run_next() is True
    assert store.passages[known]["status"] == "fini" and store.passages["inconnu"]["status"] == "en_file"
    passage_service.run_passage("inconnu")
    assert store.passages["inconnu"]["status"] == "en_file"


def test_a_failed_passage_of_an_unknown_chain_is_not_resumed_here(store, chain):
    """La reprise d'un échec d'une chaîne inconnue est refusée avec la raison, sans rien écrire."""
    _unknown_passage(store, "echec")
    with pytest.raises(PassageConflict, match="chaîne inconnue de cette version"):
        passage_service.resume_passage("inconnu")
    assert len(store.passages) == 1


# --- La chaîne des spots (services/spot_chain.py, issue #276) ---

@pytest.fixture
def spots(monkeypatch):
    """Les parties de la chaîne des spots simulées : chacune note ce qu'on lui demande ; le verrou est libre."""
    state = {"ran": [], "fail": {}}

    def run_part(passage_id, key, city, resume, check_budget):
        state["ran"].append((key, city["name"], passage_courant()))
        if key != "source":
            check_budget()      # un agent regarde le budget avant chaque spot
        if key in state["fail"]:
            raise state["fail"][key]
        return {"spots_lus": 9} if key == "source" else {"harmonises": 3}

    from contextlib import nullcontext
    monkeypatch.setattr(passage_service.spot_chain, "run_part", run_part)
    monkeypatch.setitem(passage_service.CHAINS, "spots", passage_service.Chain(
        key="spots", label="Chaîne des spots", parts=passage_service.spot_chain.PARTS, paid=True,
        lock=lambda city_id, part: nullcontext(), lock_is_free=lambda city_id, part: True, run_part=run_part,
        steps_of=passage_service.spot_chain.steps_of, free_parts=passage_service.spot_chain.FREE_PARTS))
    return state


def test_the_spot_chain_runs_its_four_parts_in_order_on_the_city_itself(store, spots):
    """La chaîne des spots passe la source, puis l'harmonisation, les ouvertures et la vérification, sous l'identifiant du passage."""
    passage_id = passage_service.create_passage("spots", 12)
    passage_service.run_passage(passage_id)
    assert [ran[0] for ran in spots["ran"]] == ["source", "harmonisation", "ouvertures", "verification"]
    assert all(ran[1] == "Guidel" and ran[2] == passage_id for ran in spots["ran"])
    passage = passage_service.read_passage(passage_id)
    assert passage["etat"] == "fini" and passage["categories"][0]["bilan_texte"] == "9 spots lus."


def test_the_source_of_the_spots_is_never_held_by_the_budget(store, spots):
    """Budget atteint : une ville ajoutée par l'ETL a quand même ses spots lus, puis le passage attend avant l'harmonisation."""
    store.budget_reason = "plafond du jour atteint : 10.40 € dépensés sur 10.00 €"
    passage_id = passage_service.create_passage("spots", 12, origin="etl")
    passage_service.run_passage(passage_id)
    assert [ran[0] for ran in spots["ran"]] == ["source"]
    assert store.passages[passage_id]["status"] == "en_file"
    assert passage_queue.why_waiting(passage_id).startswith("plafond du jour atteint")


def test_a_launch_of_agent_parts_is_refused_when_the_budget_is_reached(store, spots):
    """Budget atteint : relancer seulement l'harmonisation est refusé, relancer seulement la source ne l'est pas."""
    store.budget_reason = "plafond du jour atteint : 10.40 € dépensés sur 10.00 €"
    with pytest.raises(PassageConflict, match="Budget des agents atteint"):
        passage_service.create_passage("spots", 12, ["harmonisation"])
    assert passage_service.create_passage("spots", 12, ["source"])


def test_spots_missed_are_a_failure_resumed_without_the_finished_parts(store, spots):
    """Deux spots ratés à la vérification : la partie échoue avec la raison traduite, et la reprise ne refait qu'elle."""
    from services.spot_chain import SpotsMissed
    spots["fail"]["verification"] = SpotsMissed(2, 5, LLMTimeout("claude -p n'a pas répondu"))
    failed = passage_service.create_passage("spots", 12)
    passage_service.run_passage(failed)
    passage = passage_service.read_passage(failed)
    assert passage["etat"] == "echec"
    assert passage["raison_echec"].startswith("2 spots ratés sur 7 (délai dépassé")
    del spots["fail"]["verification"]
    spots["ran"].clear()
    resumed = passage_service.resume_passage(failed)
    passage_service.run_passage(resumed)
    assert [ran[0] for ran in spots["ran"]] == ["verification"]


def test_spots_missed_by_the_claude_quota_wait_in_the_queue(store, spots):
    """Des spots ratés parce que le quota des agents est atteint : la vérification attend son retour en file, sans échec (#332)."""
    from services.spot_chain import SpotsMissed
    spots["fail"]["verification"] = SpotsMissed(2, 5, quota())
    passage_id = passage_service.create_passage("spots", 12)
    passage_service.run_passage(passage_id)
    assert store.passages[passage_id]["status"] == "en_file"
    assert store.parts[passage_id][3]["status"] == "a_faire" and store.parts[passage_id][3]["step"] == "budget"


def test_the_source_step_reads_only_the_source_then_the_agents_step_takes_the_city(store, spots):
    """L'étape de la source lit la source seule et remet le passage en file ; l'étape des agents des spots le prend ensuite (#332)."""
    passage_id = passage_service.create_passage("spots", 12, origin="etl")
    assert passage_queue.next_for(step("agents_spots")) is None
    assert passage_queue.run_step_once(step("source")) is True
    assert [ran[0] for ran in spots["ran"]] == ["source"] and store.passages[passage_id]["status"] == "en_file"
    assert passage_queue.run_step_once(step("agents_spots")) is True
    assert [ran[0] for ran in spots["ran"]] == ["source", "harmonisation", "ouvertures", "verification"]
    assert store.passages[passage_id]["status"] == "fini"


def test_the_source_chains_the_cities_while_the_agents_wait_for_the_budget(store, spots):
    """Budget atteint : la source des spots enchaîne les villes, leurs agents attendent sans échec (#317 : spots lus le jour de l'ajout)."""
    store.budget_reason = "plafond du jour atteint"
    first = passage_service.create_passage("spots", 12, origin="etl")
    second = passage_service.create_passage("spots", 13, origin="etl")
    assert passage_queue.run_step_once(step("source")) is True
    assert passage_queue.run_step_once(step("source")) is True
    assert passage_queue.run_step_once(step("agents_spots")) is False
    assert [ran[0] for ran in spots["ran"]] == ["source", "source"]
    assert store.passages[first]["status"] == store.passages[second]["status"] == "en_file"


@pytest.mark.parametrize("summary,text", [
    ({"verifies": 0}, "0 spot vérifié."),
    ({"ouvertures_lues": 1}, "1 ouverture lue."),
    ({"harmonises": 7}, "7 spots harmonisés."),
])
def test_zero_and_one_take_the_singular_in_a_summary(summary, text):
    """Le bilan d'une partie écrit « 0 spot vérifié » et « 1 ouverture lue » au singulier, le pluriel à partir de 2 (Argol, 22 novembre 2026)."""
    assert passage_service.summary_text(summary) == text


def test_the_pepites_of_a_city_are_a_paid_chain_held_by_the_budget(store, monkeypatch):
    """La chaîne des pépites d'une ville compte comme une chaîne : budget des chaînes atteint, son lancement est refusé (décision du 22 novembre 2026)."""
    from contextlib import nullcontext
    monkeypatch.setattr(passage_service.etl_chains, "city_lock", lambda key, city_id: nullcontext())
    monkeypatch.setattr(passage_service.etl_chains, "city_lock_is_free", lambda key, city_id: True)
    monkeypatch.setattr(passage_service.pepite_chain.pepite_service, "search_city_for_chain",
                        lambda city_id: {"pepites_trouvees": 12})
    store.budget_reason = "plafond du jour atteint : 10.40 € dépensés sur 10.00 €"
    with pytest.raises(PassageConflict, match="Budget des agents atteint"):
        passage_service.create_passage("pepites", 12)
    store.budget_reason = None
    passage_id = passage_service.create_passage("pepites", 12)
    passage_service.run_passage(passage_id)
    passage = passage_service.read_passage(passage_id)
    assert passage["etat"] == "fini" and passage["payant"] is True
    assert passage["categories"][0]["bilan_texte"] == "12 pépites trouvées."
    assert passage_service.summary_text({"pepites_trouvees": 0, "zones_deja_couvertes": 1}) == (
        "0 pépite trouvée ; 1 zone déjà couverte par une recherche récente.")



# --- Ce qu'un passage a trouvé (le journal passage_items, issue #276) ---

def _journal(store, passage_id, item_id, action, part):
    """Une ligne du journal, telle que la requête la rend, avec le nom du spot."""
    store.items.append({"passage_id": passage_id, "item_type": "spot", "item_id": item_id, "action": action,
                        "part": part, "written_at": datetime(2026, 11, 22, 16, 39), "item_name": f"spot {item_id}"})


def test_a_passage_gives_what_it_found(store, chain):
    """Un passage donne ses trouvailles : chaque spot ajouté ou modifié, avec son nom et la partie qui l'a fait."""
    passage_id = passage_service.create_passage("services", 12)
    _journal(store, passage_id, 3893, "ajout", "source")
    _journal(store, passage_id, 3893, "modification", "harmonisation")
    passage = passage_service.read_passage(passage_id)
    assert passage["nombre_trouvailles"] == 2
    assert [(item["id"], item["action"], item["partie"]) for item in passage["trouvailles"]] == [
        (3893, "ajout", "source"), (3893, "modification", "harmonisation")]


def test_the_list_of_passages_counts_the_findings_without_detailing_them(store, chain):
    """La liste des passages donne le nombre de trouvailles de chacun, sans les détailler : une grande ville en a des centaines."""
    passage_id = passage_service.create_passage("services", 12, origin="etl")
    _journal(store, passage_id, 3893, "ajout", "source")
    listed = passage_service.list_passages()["en_file"][0]
    assert listed["nombre_trouvailles"] == 1 and listed["trouvailles"] is None


def test_for_an_information_the_passages_that_brought_it_are_given(store, chain):
    """Pour le spot 3893, les passages qui l'ont apporté se lisent du plus récent au plus ancien, avec ce que chacun a fait sur lui seul."""
    source = passage_service.create_passage("services", 12)
    store.set_passage_status(source, "fini")
    _journal(store, source, 3893, "ajout", "source")
    _journal(store, source, 3894, "ajout", "source")
    agents = passage_service.create_passage("services", 12)
    store.set_passage_status(agents, "fini")
    _journal(store, agents, 3893, "modification", "harmonisation")
    listed = passage_service.list_passages(item_type="spot", item_id=3893)
    assert [passage["passage_id"] for passage in listed["derniers"]] == [agents, source]
    assert [item["partie"] for item in listed["derniers"][1]["trouvailles"]] == ["source"]
    assert set(listed) == {"en_cours", "en_file", "derniers", "villes_en_attente"}


def test_a_command_line_passage_is_given_as_an_origin_too(store, chain):
    """Un spot harmonisé en ligne de commande a pour origine un passage sans trace dans passages : il est donné quand même, avec son coût."""
    _journal(store, "ligne_de_commande", 1435, "modification", "harmonisation")
    store.calls["ligne_de_commande"] = [{"agent": "harmonize_spots", "etape": None, "status": "reussi",
                                         "cost_usd": 0.02, "called_at": datetime(2026, 11, 10), "engine": "api"}]
    origin = passage_service.list_passages(item_type="spot", item_id=1435)["derniers"][0]
    assert origin["passage_id"] == "ligne_de_commande" and origin["chaine"] is None and origin["appels"] == 1
    assert origin["trouvailles"][0]["partie"] == "harmonisation"


@pytest.mark.parametrize("item_type,item_id", [("restaurant", 3), ("spot", None)])
def test_an_unknown_or_incomplete_object_is_refused(store, chain, item_type, item_id):
    """Un objet d'un type inconnu, ou sans son id, est refusé avec les types attendus."""
    with pytest.raises(ValueError, match="service, spot, pepite"):
        passage_service.list_passages(item_type=item_type, item_id=item_id)


# --- Les chaînes de l'ajout d'une ville, demandées une seule fois (issue #316) ---

@pytest.fixture
def city_chains(store, free, monkeypatch):
    """Les chaînes de l'ajout d'une ville, avec Guidel jamais lue par la source des spots, sauf si `read` est vrai."""
    state = {"read": False}
    monkeypatch.setattr(passage_service.spot_chain, "source_already_read", lambda city_id: state["read"])
    return state


def test_a_new_city_asks_a_free_chain_once_with_all_its_parts(store, city_chains):
    """La première rando d'une ville nouvelle met OSM dans la file, d'origine « etl », avec toutes ses parties."""
    passage_id = passage_service.request_city_chain("osm", "Guidel")
    passage = store.passages[passage_id]
    assert passage["chain"] == "osm" and passage["origin"] == "etl" and passage["status"] == "en_file"
    assert [row["part"] for row in store.parts[passage_id]] == ["osm"]


def test_five_hikes_in_the_same_new_city_ask_each_chain_only_once(store, city_chains):
    """Cinq randos envoyées ensemble à la même ville ne demandent qu'un OSM et qu'un FINESS (Île-d'Yeu, 23 novembre 2026 : cinq OSM, trois FINESS)."""
    for _ in range(5):
        passage_service.request_city_chain("osm", "Guidel")
        passage_service.request_city_chain("finess", "Guidel")
    assert sorted(passage["chain"] for passage in store.passages.values()) == ["finess", "osm"]


def test_a_chain_already_finished_on_the_city_is_not_asked_again(store, city_chains):
    """Une rando arrivée après la fin d'OSM sur sa ville ne relance pas OSM : la ville est déjà faite."""
    first = passage_service.request_city_chain("osm", "Guidel")
    passage_service.run_passage(first)
    assert store.passages[first]["status"] == "fini"
    assert passage_service.request_city_chain("osm", "Guidel") is None


def test_a_failure_waiting_for_its_resume_is_not_asked_again(store, city_chains, free):
    """OSM en échec sur la ville, pas encore repris : une seconde rando n'en demande pas un autre, la reprise s'en charge."""
    free["loaded"]["osm"] = None
    failed = passage_service.request_city_chain("osm", "Guidel")
    passage_service.run_passage(failed)
    assert store.passages[failed]["status"] == "echec"
    assert passage_service.request_city_chain("osm", "Guidel") is None


def test_a_city_already_read_does_not_read_the_source_of_the_spots_again(store, city_chains):
    """Une ville dont la source des spots a été lue avant les passages (histo_scrap) ne demande que les parties d'agents."""
    city_chains["read"] = True
    passage_id = passage_service.request_city_chain("spots", "Guidel")
    assert [row["part"] for row in store.parts[passage_id]] == ["harmonisation", "ouvertures", "verification"]


def test_a_city_unknown_to_cities_asks_nothing(store, city_chains):
    """Une ville absente de la table cities ne met rien dans la file : l'avertissement est écrit dans le journal."""
    assert passage_service.request_city_chain("osm", "Ville inconnue") is None
    assert store.passages == {}


def test_the_osm_of_two_new_cities_pass_one_after_the_other(store, city_chains, free, monkeypatch):
    """Deux villes nouvelles : la file fait passer leurs OSM l'un après l'autre, jamais en même temps (62 OSM dans la même minute le 23 novembre 2026)."""
    morgat = {"id": 13, "name": "Morgat", "commune": "Crozon", "insee": "29042"}
    monkeypatch.setattr(passage_service.service_store, "load_cities", lambda: [CITY, morgat])
    guidel = passage_service.request_city_chain("osm", "Guidel")
    second = passage_service.request_city_chain("osm", "Morgat")
    store.passages[second]["city_name"] = "Morgat"
    assert run_next() is True
    assert store.passages[guidel]["status"] == "fini" and store.passages[second]["status"] == "en_file"
    assert run_next() is True
    assert free["asked"] == [("osm", "Guidel"), ("osm", "Morgat")]


# --- La reprise seule des chaînes gratuites en échec (services/passage_queue.py, issue #316) ---

NOW = datetime(2026, 11, 25, 12, 0)


def _failed_osm(store, free, finished_at, resumed_from=None):
    """Un OSM de l'ETL sur Guidel, en échec (OpenStreetMap muet), fini à `finished_at`."""
    free["loaded"]["osm"] = None
    passage_id = passage_service.create_passage("osm", 12, origin="etl", resumed_from=resumed_from)
    passage_service.run_passage(passage_id)
    store.passages[passage_id]["finished_at"] = finished_at
    return passage_id


def test_a_failed_osm_is_resumed_by_the_queue_after_fifteen_minutes(store, free):
    """OSM en échec depuis 20 minutes : la file le reprend seule, par un passage « etl » qui le désigne, sans script (25 novembre 2026)."""
    failed = _failed_osm(store, free, datetime(2026, 11, 25, 11, 40))
    [resumed] = passage_queue.resume_failed_free_chains(NOW)
    assert store.passages[resumed]["resumed_from"] == failed and store.passages[resumed]["origin"] == "etl"
    assert store.passages[resumed]["status"] == "en_file"


def test_a_failure_too_recent_waits_before_its_resume(store, free):
    """OSM en échec depuis 5 minutes n'est pas encore repris : OpenStreetMap a le temps de se remettre."""
    _failed_osm(store, free, datetime(2026, 11, 25, 11, 55))
    assert passage_queue.resume_failed_free_chains(NOW) == []


def test_after_two_resumes_the_failure_waits_for_the_admin(store, free):
    """Un OSM qui échoue encore après deux reprises n'est plus repris seul : l'échec attend l'administratrice."""
    first = _failed_osm(store, free, datetime(2026, 11, 25, 10, 0))
    second = _failed_osm(store, free, datetime(2026, 11, 25, 10, 30), resumed_from=first)
    _failed_osm(store, free, datetime(2026, 11, 25, 11, 0), resumed_from=second)
    assert passage_queue.resume_failed_free_chains(NOW) == []


def test_a_failure_already_redone_by_hand_is_not_resumed(store, free):
    """OSM en échec, mais déjà rechargé sur la ville par une relance à la main : la file ne le refait pas."""
    _failed_osm(store, free, datetime(2026, 11, 25, 11, 0))
    free["loaded"]["osm"] = 40
    by_hand = passage_service.create_passage("osm", 12)
    passage_service.run_passage(by_hand)
    assert passage_queue.resume_failed_free_chains(NOW) == []


def test_two_failures_on_the_same_city_are_resumed_once(store, free):
    """Deux OSM en échec sur la même ville (doublons d'avant #316, Larrau) : un seul est repris, pas deux en file (#329)."""
    _failed_osm(store, free, datetime(2026, 11, 25, 11, 0))
    _failed_osm(store, free, datetime(2026, 11, 25, 11, 5))
    assert len(passage_queue.resume_failed_free_chains(NOW)) == 1


def test_a_failure_is_not_resumed_while_the_chain_is_queued_on_the_city(store, free):
    """OSM en échec alors qu'un autre OSM de la ville est déjà en file : la file ne le reprend pas (#329)."""
    _failed_osm(store, free, datetime(2026, 11, 25, 11, 0))
    passage_service.create_passage("osm", 12, origin="etl")
    assert passage_queue.resume_failed_free_chains(NOW) == []


def test_a_failure_older_than_a_day_is_not_resumed(store, free):
    """Un échec de la veille n'est pas repris seul : l'administratrice a peut-être déjà décidé de le laisser."""
    _failed_osm(store, free, datetime(2026, 11, 24, 9, 0))
    assert passage_queue.resume_failed_free_chains(NOW) == []


def test_a_failed_paid_chain_is_never_resumed_alone(store, chain):
    """Un passage des services en échec n'est jamais repris par la file : une reprise coûte, c'est l'admin qui décide."""
    chain["fail"]["restaurants"] = LLMTimeout("délai dépassé")
    failed = passage_service.create_passage("services", 12, ["restaurants"], origin="etl")
    passage_service.run_passage(failed)
    store.passages[failed]["finished_at"] = datetime(2026, 11, 25, 10, 0)
    assert passage_queue.resume_failed_free_chains(NOW) == []


# --- La reprise seule d'une source des spots en échec (services/passage_queue.py, issue #344) ---

def _failed_spots(store, spots, part, finished_at):
    """Un passage des spots de l'ETL sur Guidel, en échec sur cette partie, fini à `finished_at`."""
    from services.etl_chains import StepFailed
    spots["fail"][part] = StepFailed("source des spots illisible") if part == "source" else LLMTimeout("trop long")
    passage_id = passage_service.create_passage("spots", 12, origin="etl")
    passage_service.run_passage(passage_id)
    del spots["fail"][part]
    store.passages[passage_id]["finished_at"] = finished_at
    return passage_id


def test_a_failed_source_of_the_spots_is_resumed_by_the_queue(store, spots):
    """Une source des spots en échec depuis 20 minutes est reprise seule, sans clic (53 sources en échec le 27 novembre 2026)."""
    failed = _failed_spots(store, spots, "source", datetime(2026, 11, 25, 11, 40))
    [resumed] = passage_queue.resume_failed_free_chains(NOW)
    assert store.passages[resumed]["resumed_from"] == failed and store.passages[resumed]["origin"] == "etl"
    assert [row["part"] for row in store.parts[resumed]] == ["source", "harmonisation", "ouvertures", "verification"]


@pytest.mark.parametrize("part", ["harmonisation", "ouvertures", "verification"])
def test_spots_failed_on_a_paid_part_wait_for_the_admin(store, spots, part):
    """Des spots en échec sur une partie payante ne sont jamais repris seuls : une reprise coûte, l'administratrice décide."""
    _failed_spots(store, spots, part, datetime(2026, 11, 25, 11, 40))
    assert passage_queue.resume_failed_free_chains(NOW) == []


def test_a_failed_source_is_not_resumed_while_the_spots_of_the_city_are_queued(store, spots):
    """Une source en échec n'est pas reprise quand les spots de la ville sont déjà en file : ils la liront."""
    _failed_spots(store, spots, "source", datetime(2026, 11, 25, 11, 40))
    passage_service.create_passage("spots", 12, origin="etl")
    assert passage_queue.resume_failed_free_chains(NOW) == []


def test_a_failed_source_is_not_resumed_once_the_source_was_read_since(store, spots):
    """Une source en échec n'est pas reprise quand la source de la ville a été lue depuis, par une relance à la main."""
    _failed_spots(store, spots, "source", datetime(2026, 11, 25, 11, 40))
    by_hand = passage_service.create_passage("spots", 12, ["source"])
    passage_service.run_passage(by_hand)
    assert passage_queue.resume_failed_free_chains(NOW) == []


def test_a_failed_source_is_resumed_twice_at_most(store, spots):
    """Une source qui échoue encore après deux reprises n'est plus reprise seule, comme les chaînes gratuites."""
    first = _failed_spots(store, spots, "source", datetime(2026, 11, 25, 10, 0))
    second = _failed_spots(store, spots, "source", datetime(2026, 11, 25, 10, 30))
    third = _failed_spots(store, spots, "source", datetime(2026, 11, 25, 11, 0))
    store.passages[second]["resumed_from"], store.passages[third]["resumed_from"] = first, second
    assert passage_queue.resume_failed_free_chains(NOW) == []
