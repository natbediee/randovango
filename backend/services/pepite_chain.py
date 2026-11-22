"""
La chaîne des pépites d'une ville (issue #276) : les lieux incontournables autour de la ville, cherchés par Vany puis
placés sur la carte. Elle se lance, se suit et se reprend comme les autres chaînes (services/passage_service.py).

UNE PARTIE
    lieux   Vany cherche les lieux (agent discover_places), puis le code les recale sur les lieux d'OSM, et l'agent
            locate_pepites retrouve la position de ceux qu'il n'a pas su placer. Une zone qu'une recherche récente
            couvre déjà n'est pas recherchée : relancer une ville ne coûte rien tant que sa recherche est récente.

Les pépites d'un jour de voyage (l'agenda, le choix du jour) ne passent pas par cette chaîne : elles dépendent du
voyage, pas de la ville, et partent quand le voyageur choisit sa ville ou son spot (services/pepite_service.py).

PAYANTE, COMME UNE CHAÎNE
Elle compte dans le budget des chaînes, et s'arrête quand il est atteint ; la part gardée pour Vany reste aux voyageurs
(décision de l'utilisatrice, 22 novembre 2026). Deux villes peuvent la passer en même temps : un verrou par ville.
"""
from services import pepite_service

PARTS = {"lieux": "Lieux incontournables autour de la ville"}
# Les agents de la partie, tels qu'ils sont notés dans llm_calls : l'étape affichée se lit dans leurs appels.
STEPS = {"discover_places": "recherche", "locate_pepites": "position"}


def steps_of(part: str) -> dict:
    """Les deux agents de la partie « lieux » et l'étape que fait chacun."""
    return STEPS


def run_part(passage_id: str, key: str, city: dict, resume: bool, check_budget) -> dict:
    """La partie « lieux » sur la ville : son bilan, ou l'erreur de Vany qui remonte."""
    return pepite_service.search_city_for_chain(city["id"])
