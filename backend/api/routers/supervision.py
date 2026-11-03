from fastapi import APIRouter, Body, Depends, HTTPException

from api.routers.etl import get_current_user
from services import poi_review_service, supervision_service
from services.authentification import get_roles_for_user

router = APIRouter()


def require_admin(user=Depends(get_current_user)) -> dict:
    """Réservé aux admins. Les rôles sont relus en base : un rôle retiré vaut tout de suite."""
    if "admin" not in get_roles_for_user(user["user_id"]):
        raise HTTPException(status_code=403, detail="Accès refusé : rôle admin requis")
    return user


@router.get("/reviews", summary="Agents' proposals awaiting a human decision.")
def get_reviews(_admin=Depends(require_admin)):
    return supervision_service.get_reviews()


@router.post("/decisions", summary="Records a human decision on a proposal.")
def post_decision(data: dict = Body(...), admin=Depends(require_admin)):
    """
    data = {"objet_id": 1368, "decision": "garder", "note": "Vu sur Street View", "a_savoir": "..."}
    "a_savoir" (facultatif) : le texte corrigé, une phrase par ligne ; absent, celui de l'agent reste.
    """
    if data.get("decision") not in supervision_service.DECISIONS or not isinstance(data.get("objet_id"), int):
        raise HTTPException(status_code=422, detail="Décision invalide")
    supervision_service.decide(data["objet_id"], data["decision"], data.get("note") or "", admin["username"],
                               data.get("a_savoir"))
    return supervision_service.get_reviews()


@router.put("/decisions/{decision_id}", summary="Corrects the text kept by a decision.")
def put_decision(decision_id: int, data: dict = Body(...), _admin=Depends(require_admin)):
    """data = {"a_savoir": "..."} : une phrase par ligne, vide s'il n'y a plus rien à signaler."""
    if not isinstance(data.get("a_savoir"), str):
        raise HTTPException(status_code=422, detail="Texte invalide")
    supervision_service.correct_a_savoir(decision_id, data["a_savoir"])
    return supervision_service.get_reviews()


@router.delete("/decisions/{decision_id}", summary="Cancels a decision; it stays recorded.")
def delete_decision(decision_id: int, _admin=Depends(require_admin)):
    supervision_service.cancel_decision(decision_id)
    return supervision_service.get_reviews()


@router.get("/services", summary="Service checks awaiting a human decision, one queue at a time.")
def get_service_reviews(tab: str = "liens", service: str | None = None, ville: str | None = None,
                        _admin=Depends(require_admin)):
    try:
        return poi_review_service.get_reviews(tab, service or None, ville or None)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))


@router.post("/services/decisions", summary="Records and applies a decision on one place or a batch of checked links.")
def post_service_decision(data: dict = Body(...), admin=Depends(require_admin)):
    """data = {"tab": "liens", "poi_ids": [12, 13], "action": "valider_lien", "note": "", "mois": [3, 4]}"""
    poi_ids = data.get("poi_ids")
    if not isinstance(poi_ids, list) or not poi_ids or not all(isinstance(poi_id, int) for poi_id in poi_ids):
        raise HTTPException(status_code=422, detail="Lieux invalides")
    try:
        poi_review_service.decide(data.get("tab"), poi_ids, data.get("action"), data.get("note") or "",
                                  admin["username"], data.get("mois"))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    return poi_review_service.get_reviews(data["tab"], data.get("service") or None,
                                          data.get("ville") or None)


@router.post("/services/audit/{decision_id}", summary="Marks a rule decision as checked by a human.")
def post_service_audit(decision_id: int, tab: str = "liens", service: str | None = None, ville: str | None = None,
                       _admin=Depends(require_admin)):
    poi_review_service.confirm_audit(decision_id)
    return poi_review_service.get_reviews(tab, service or None, ville or None)


@router.delete("/services/decisions/{decision_id}", summary="Cancels a service decision and restores the place.")
def delete_service_decision(decision_id: int, tab: str = "liens", service: str | None = None,
                            ville: str | None = None, _admin=Depends(require_admin)):
    try:
        poi_review_service.cancel_decision(decision_id)
        return poi_review_service.get_reviews(tab, service or None, ville or None)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
