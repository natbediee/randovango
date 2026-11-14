from fastapi import APIRouter, Body, Depends, HTTPException

from api.dependencies import require_admin
# Les routes de décision renvoient encore la liste de leur page : elles la lisent comme les routes de relecture
# et de recherche.
# Ce renvoi disparaît quand une décision ne répond plus que par elle-même (plan de #186, 2.1).
from api.routers.supervision_reviews import service_reviews
from api.routers.supervision_search import service_search
# La note de la proposition se vérifie comme pour un spot ; ce fichier disparaît au commit suivant (plan de #186).
from api.routers.supervision_decisions import checked_rating
from services.supervision import services_edit, services_review

router = APIRouter()


@router.post("/services/decisions", summary="Records and applies a decision on one place or a batch of checked links.")
def post_service_decision(data: dict = Body(...), admin=Depends(require_admin)):
    """
    data = {"tab": "fermetures", "poi_ids": [2686], "action": "retirer", "note": "", "mois": None, "url": None,
            "nom": None, "pertinence": "a_corriger", "raison": "nom_adresse"}
    poi_ids : un seul lieu, ou un lot de liens contrôlés (« liens », « valider_lien »), qui n'est pas noté.
    "pertinence" et "raison" (facultatives) : la note de la proposition de l'agent, pour un seul lieu.
    """
    poi_ids = data.get("poi_ids")
    if not isinstance(poi_ids, list) or not poi_ids or not all(isinstance(poi_id, int) for poi_id in poi_ids):
        raise HTTPException(status_code=422, detail="Lieux invalides")
    pertinence, raison = checked_rating(data.get("pertinence"), data.get("raison"))
    if pertinence and len(poi_ids) > 1:
        # Une décision par lot (liens cochés) n'est pas notée : la note juge une proposition, pas un lot.
        raise HTTPException(status_code=400, detail="Une décision par lot ne se note pas")
    try:
        services_review.decide(data.get("tab"), poi_ids, data.get("action"), data.get("note") or "",
                                  admin["username"], data.get("mois"), data.get("url"), data.get("nom"),
                                  pertinence, raison)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    # La page peut montrer toutes les files (« vue ») : on la renvoie telle qu'elle était.
    return service_reviews(data.get("vue") or data["tab"], data.get("service") or None,
                            data.get("ville") or None, data.get("type") or None, data.get("commune") or None)


# Onglet « Modifier » : corriger n'importe quel lieu, même sans signal (services_edit).
# Chaque réponse renvoie la recherche telle qu'elle était (supervision_search), avec la correction appliquée.

@router.post("/edit/services/decisions", summary="Applies and records a correction on one place.")
def post_edit_service(data: dict = Body(...), admin=Depends(require_admin)):
    """data = {"poi_id": 32498, "action": "autre_nom", "nom": "Cave de Keruzas", "url": None, "mois": [], "note": "",
    "ville": 12, "commune": "", "service": "commerce", "type": "", "nom_recherche": "keruzas"}"""
    if not isinstance(data.get("poi_id"), int):
        raise HTTPException(status_code=422, detail="Lieu invalide")
    try:
        services_edit.decide(data["poi_id"], data.get("action"), data.get("note") or "", admin["username"],
                                data.get("mois"), data.get("url"), data.get("nom"))
        return service_search({**data, "nom": data.get("nom_recherche")})
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
