"""
Le prix d'un appel fait par l'API d'Anthropic, en dollars (issue #275).

POURQUOI CE FICHIER
Le programme `claude` (moteur claude-code, abonnement) donne lui-même ce qu'aurait coûté l'appel (total_cost_usd).
L'API, elle, ne donne que les tokens consommés et le nombre de recherches web : le prix se calcule ici, avec le tarif
publié par Anthropic. Sans lui, llm_calls.cost_usd restait vide pour le moteur API, et le budget des agents comptait
ces appels pour rien.

LE TARIF
En dollars pour un million de tokens, par modèle. Relevé le 20 novembre 2026 sur la page des prix d'Anthropic : à
mettre à jour quand Anthropic change ses prix ou quand un agent passe à un nouveau modèle.
    - input : les tokens envoyés, hors cache ;
    - output : les tokens écrits par Claude, réflexion comprise ;
    - cache_read : les tokens relus dans le cache (les consignes, mises en cache par llm_service.py).
L'écriture dans le cache coûte 1,25 fois le prix d'entrée (cache de 5 minutes, celui que demande llm_service.py), une
recherche web 10 $ les 1 000, et les tokens d'un appel groupé (Batch API, moteur api-batch) la moitié du prix.
"""
from utils.logger_util import LoggerUtil

logger = LoggerUtil.get_logger("llm_service")

PRICES_PER_MILLION = {
    "claude-fable-5-2": {"input": 8.00, "output": 40.00, "cache_read": 0.20},
    "claude-opus-5-5": {"input": 4.00, "output": 20.00, "cache_read": 0.20},
    "claude-sonnet-5-5": {"input": 2.00, "output": 10.00, "cache_read": 0.10},
    # Haiku 5.5 coûte plus cher au-delà de 100 000 tokens envoyés ; nos consignes sont bien plus courtes.
    "claude-haiku-5-5": {"input": 0.10, "output": 0.50, "cache_read": 0.01},
}
CACHE_WRITE_FACTOR = 1.25
WEB_SEARCH_PRICE = 10.00 / 1000
BATCH_FACTOR = 0.5


def api_cost_usd(model: str, measures: dict, batch: bool = False) -> float | None:
    """
    Le prix en dollars d'un appel fait par l'API, d'après ses mesures (les tokens et recherches web de
    llm_service.usage_measures). None si le modèle n'a pas de tarif ici : le journal le signale, pour qu'on l'ajoute.
    Un appel sans aucune mesure (l'API n'a pas répondu) coûte 0.
    """
    prices = PRICES_PER_MILLION.get(model)
    if prices is None:
        logger.warning(f"[llm] Pas de tarif pour le modèle {model} : coût de l'appel inconnu (agents/llm_prices.py)")
        return None
    tokens_cost = ((measures.get("input_tokens") or 0) * prices["input"]
                   + (measures.get("output_tokens") or 0) * prices["output"]
                   + (measures.get("cache_read_tokens") or 0) * prices["cache_read"]
                   + (measures.get("cache_write_tokens") or 0) * prices["input"] * CACHE_WRITE_FACTOR) / 1_000_000
    if batch:
        tokens_cost = tokens_cost * BATCH_FACTOR  # la remise des lots porte sur les tokens, pas sur les recherches web
    return round(tokens_cost + (measures.get("web_searches") or 0) * WEB_SEARCH_PRICE, 4)
