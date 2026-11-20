"""Le prix d'un appel fait par l'API d'Anthropic, en dollars (agents/llm_prices.py, issue #275)."""
import pytest

from agents.llm_prices import api_cost_usd

# Un appel d'un million de tokens de chaque sorte, et 100 recherches web : les prix se lisent sans calcul.
MILLION_OF_EACH = {"input_tokens": 1_000_000, "output_tokens": 1_000_000, "cache_read_tokens": 1_000_000,
                   "cache_write_tokens": 1_000_000, "web_searches": 100}


def test_every_kind_of_token_and_the_web_searches_are_priced():
    """Un appel en Opus 5.5 paie l'entrée (4 $), la sortie (20 $), la relecture du cache (0,20 $), l'écriture du cache (5 $) et 100 recherches web (1 $)."""
    assert api_cost_usd("claude-opus-5-5", MILLION_OF_EACH) == pytest.approx(30.20)


def test_a_batch_call_pays_half_of_its_tokens_but_all_its_web_searches():
    """Un appel groupé (Batch API) paie ses tokens moitié prix, mais ses recherches web au prix plein."""
    assert api_cost_usd("claude-opus-5-5", MILLION_OF_EACH, batch=True) == pytest.approx(29.20 / 2 + 1)


def test_a_call_without_any_answer_costs_nothing():
    """Un appel auquel l'API n'a pas répondu n'a aucune mesure, et ne coûte rien."""
    assert api_cost_usd("claude-sonnet-5-5", {}) == 0


def test_a_model_without_a_price_gives_an_unknown_cost():
    """Un modèle absent du tarif donne un coût inconnu (None) plutôt qu'un faux zéro."""
    assert api_cost_usd("modele-inconnu", MILLION_OF_EACH) is None
