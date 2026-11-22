"""
La chaîne des spots d'une ville (services/spot_chain.py, issue #276) : la source relue, puis les trois agents limités
aux spots de la ville encore à faire. Ni base, ni navigateur, ni agent : chaque étape est remplacée.
"""
import pytest

from services import spot_chain
from services.etl_chains import StepFailed
from services.spot_chain import SpotsMissed

GUIDEL = {"id": 12, "name": "Guidel"}


def test_the_source_reads_the_city_and_gives_the_number_of_spots(monkeypatch):
    """La source des spots est relue autour de Guidel, chargée sous son nom, et le bilan dit combien de spots ont été lus."""
    loaded = []
    monkeypatch.setattr(spot_chain, "run_p4n_scraper", lambda name, is_headless, save_csv: ["brut"])
    monkeypatch.setattr(spot_chain, "transform_p4n", lambda raw: ["spot 1", "spot 2"])
    monkeypatch.setattr(spot_chain, "load_p4n_to_mysql", lambda spots, name: loaded.append((spots, name)))
    assert spot_chain.run_source("p1", "source", GUIDEL, False, lambda: None) == {"spots_lus": 2}
    assert loaded == [(["spot 1", "spot 2"], "Guidel")]


def test_an_unreadable_source_fails_with_its_reason(monkeypatch):
    """Une source des spots qui ne répond pas devient un échec avec sa raison, et rien n'est chargé."""
    monkeypatch.setattr(spot_chain, "run_p4n_scraper", lambda name, is_headless, save_csv: None)
    with pytest.raises(StepFailed, match="source des spots illisible"):
        spot_chain.run_source("p1", "source", GUIDEL, False, lambda: None)


@pytest.mark.parametrize("part,module,function,key", [
    ("harmonisation", "harmonize_spots", "run_sample", "harmonises"),
    ("ouvertures", "read_openings", "run", "ouvertures_lues"),
    ("verification", "verify_spots", "run", "verifies"),
])
def test_each_agent_works_on_the_city_with_the_budget(monkeypatch, part, module, function, key):
    """Chaque agent reçoit la ville et la vérification du budget, et son bilan devient celui de la partie."""
    asked = {}

    def agent(**kwargs):
        asked.update(kwargs)
        return {"faits": 4, "rates": 0, "erreur": None}

    monkeypatch.setattr(getattr(spot_chain, module), function, agent)
    budget = lambda: None  # noqa: E731
    assert spot_chain.run_part("p1", part, GUIDEL, False, budget) == {key: 4}
    assert asked["city_id"] == 12 and asked["check_budget"] is budget
    # La règle « pas encore fait » : l'harmonisation et la vérification ne prennent que les spots jamais traités.
    assert asked.get("only_new", True) is True


def test_spots_missed_make_the_part_fail_with_the_last_error(monkeypatch):
    """Deux spots ratés sur six (quota) : la partie échoue avec le nombre et l'erreur, au lieu de se dire finie."""
    quota = RuntimeError("You've hit your session limit · resets 1:40pm (UTC)")
    monkeypatch.setattr(spot_chain.harmonize_spots, "run_sample",
                        lambda **kwargs: {"faits": 4, "rates": 2, "erreur": quota})
    with pytest.raises(SpotsMissed) as missed:
        spot_chain.run_part("p1", "harmonisation", GUIDEL, False, lambda: None)
    assert missed.value.missed == 2 and missed.value.done == 4 and missed.value.cause is quota


def test_the_step_of_an_agent_part_is_read_from_its_calls():
    """L'étape d'une partie se lit dans les appels de son agent ; la source n'en a aucun."""
    assert spot_chain.steps_of("harmonisation") == {"harmonize_spots": "harmonisation"}
    assert spot_chain.steps_of("source") == {}
