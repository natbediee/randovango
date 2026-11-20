"""
Les bornes de ce que l'API accepte sur les routes du voyage (OWASP API4, consommation de ressources).

Sans bornes, quelqu'un qui écrit lui-même ses requêtes, sans passer par la page, peut demander un séjour
de 10 000 jours (10 000 lignes écrites), le jour 999 d'un séjour de 3 jours (Vany se met au travail pour
un jour qui n'existe pas), un rayon de 5 000 km (toute la base lue d'un coup) ou les idées de Vany pour
des centaines de randos. Chaque refus répond 422 avec un message en français, AVANT toute lecture
ou écriture en base et avant toute recherche de Vany.

Les nombres viennent de l'offre gratuite : un séjour de 7 jours au plus, une rando par jour.
Les séjours plus longs viendront avec l'offre payante.
"""
from fastapi import HTTPException

from services.plan_service import get_trip_duration

# Un séjour gratuit dure 7 jours au plus : c'est aussi la portée des prévisions météo (J+0 à J+6).
MAX_FREE_TRIP_DAYS = 7
# Le rayon de recherche autour d'une ville. La page envoie toujours 5 km ; 25 km couvrent large
# autour d'une ville sans lire toute la base.
DEFAULT_RADIUS_KM = 5
MAX_RADIUS_KM = 25
# Les idées « sur le chemin » de Vany se demandent pour les randos d'un séjour : une par jour, 7 au plus.
MAX_TRAIL_TIPS_HIKES = 7

TRIP_TOO_LONG_MESSAGE = (f"Un séjour gratuit dure {MAX_FREE_TRIP_DAYS} jours au plus. "
                         "Les séjours plus longs viendront avec l'offre payante.")
RADIUS_MESSAGE = f"Le rayon de recherche va de 0 à {MAX_RADIUS_KM} km."
TOO_MANY_HIKES_MESSAGE = f"Les idées de Vany se demandent pour {MAX_TRAIL_TIPS_HIKES} randos au plus."


def refuse(message: str) -> None:
    """Refuse la requête : 422 veut dire « j'ai compris ta demande, mais cette valeur n'est pas acceptée »."""
    raise HTTPException(status_code=422, detail=message)


def check_trip_duration(duration_days: int) -> None:
    """Refuse un séjour de plus de 7 jours, avant que create_plan écrive ses jours en base."""
    if duration_days > MAX_FREE_TRIP_DAYS:
        refuse(TRIP_TOO_LONG_MESSAGE)


def check_day_in_trip(plan_id: int, day_number) -> None:
    """
    Refuse un numéro de jour qui n'est pas dans le séjour (jour 0, jour 9 d'un séjour de 7 jours, « abc »).
    Sans ce contrôle, update_plan créait la ligne du jour 999, et Vany cherchait des idées pour ce jour.
    La durée est relue en base : c'est celle choisie à la création du voyage, pas ce qu'envoie le navigateur.
    """
    # bool est un cas particulier d'int en Python (True vaut 1) : on ne l'accepte pas comme numéro de jour.
    if not isinstance(day_number, int) or isinstance(day_number, bool):
        refuse("Le numéro du jour doit être un nombre entier.")
    duration_days = get_trip_duration(plan_id)
    if not 1 <= day_number <= duration_days:
        refuse(f"Le jour {day_number} ne fait pas partie de ce séjour de {duration_days} jours.")


def check_radius(distance_km: float) -> None:
    """
    Refuse un rayon de recherche nul, négatif ou de plus de 25 km.
    Écrit « pas entre 0 et 25 » plutôt que deux comparaisons : une valeur « nan » (pas un nombre),
    qu'on peut taper dans l'adresse, échoue à toute comparaison et serait sinon acceptée.
    """
    if not 0 < distance_km <= MAX_RADIUS_KM:
        refuse(RADIUS_MESSAGE)


def check_trail_tips_count(hike_ids: list) -> None:
    """Refuse de demander les idées de Vany pour plus de 7 randos d'un coup."""
    if len(hike_ids) > MAX_TRAIL_TIPS_HIKES:
        refuse(TOO_MANY_HIKES_MESSAGE)
