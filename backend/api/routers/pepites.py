from fastapi import APIRouter, Body, Query

from services import pepite_service

router = APIRouter()


@router.get("/", summary="Returns Vany's ideas (pépites) for a trip day.")
def get_pepites(plan_id: int = Query(...), day_number: int = Query(...)):
    """
    Contenu de l'étape « Les pépites de Vany » pour un jour : 'recherche', 'propositions',
    'rien' ou 'vide' (voir pepite_service.get_day_state).
    La page rappelle cette route tant que l'état vaut 'recherche'.
    """
    return pepite_service.get_day_state(plan_id, day_number)


@router.get("/trail-tips", summary="Vany's « on the way » recommendations for hikes.")
def get_trail_tips(hike_ids: str = Query(..., description="Identifiants des randos, séparés par des virgules")):
    """
    Lieux repérés par Vany à moins de 400 m du tracé de chaque rando, pour les
    recommander dès le choix de la rando (étape 2) : {"12": [{nom, description,
    latitude, longitude}, ...]}.
    """
    ids = [int(part) for part in hike_ids.split(",") if part.strip().isdigit()]
    return pepite_service.trail_tips_for_hikes(ids)


@router.get("/news", summary="Vany's new ideas for a trip, not seen yet.")
def get_news(plan_id: int = Query(...)):
    """Idées du séjour arrivées après le passage du voyageur : rappel de la barre du bas."""
    return pepite_service.day_news(plan_id)


@router.put("/seen/{plan_id}", summary="The traveller saw the ideas of a trip day.")
def mark_seen(plan_id: int, data: dict = Body(...)):
    """data = {"day_number": 2} : le rappel de ce jour disparaît."""
    pepite_service.mark_seen(plan_id, data.get("day_number", 1))
    return {"ok": True}


@router.put("/choose/{plan_id}", summary="Adds an idea to a trip day, or removes it.")
def choose_pepite(plan_id: int, data: dict = Body(...)):
    """
    data = {"day_number": 2, "pepite_id": 15, "added": true} pour ajouter une idée
    à la journée, "added": false pour la retirer. Plusieurs idées peuvent être ajoutées.
    """
    day_number = data.get("day_number", 1)
    pepite_service.set_added(plan_id, day_number, data["pepite_id"], bool(data.get("added", True)))
    return pepite_service.get_day_state(plan_id, day_number)
