from fastapi import APIRouter, Body, Depends, HTTPException

from api.routers.etl import get_current_user
from services import poi_edit_service, poi_review_service, spot_edit_service, supervision_service
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


@router.delete("/openings/{decision_id}", summary="Cancels an opening decision and restores the previous values.")
def delete_opening_decision(decision_id: int, _admin=Depends(require_admin)):
    supervision_service.cancel_opening_decision(decision_id)
    return supervision_service.get_reviews()


@router.get("/services", summary="Service checks awaiting a human decision, one queue at a time.")
def get_service_reviews(tab: str = "liens", service: str | None = None, ville: str | None = None, type: str | None = None,
                        _admin=Depends(require_admin)):
    try:
        return poi_review_service.get_reviews(tab, service or None, ville or None, type or None)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))


@router.post("/services/decisions", summary="Records and applies a decision on one place or a batch of checked links.")
def post_service_decision(data: dict = Body(...), admin=Depends(require_admin)):
    """data = {"tab": "liens", "poi_ids": [12, 13], "action": "valider_lien", "note": "", "mois": [3, 4], "url": None, "nom": None}"""
    poi_ids = data.get("poi_ids")
    if not isinstance(poi_ids, list) or not poi_ids or not all(isinstance(poi_id, int) for poi_id in poi_ids):
        raise HTTPException(status_code=422, detail="Lieux invalides")
    try:
        poi_review_service.decide(data.get("tab"), poi_ids, data.get("action"), data.get("note") or "",
                                  admin["username"], data.get("mois"), data.get("url"), data.get("nom"))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    # La page peut montrer toutes les files (« vue ») : on la renvoie telle qu'elle était.
    return poi_review_service.get_reviews(data.get("vue") or data["tab"], data.get("service") or None,
                                          data.get("ville") or None, data.get("type") or None)


@router.post("/services/audit/{decision_id}", summary="Marks a rule decision as checked by a human.")
def post_service_audit(decision_id: int, tab: str = "liens", service: str | None = None, ville: str | None = None,
                       type: str | None = None, _admin=Depends(require_admin)):
    poi_review_service.confirm_audit(decision_id)
    return poi_review_service.get_reviews(tab, service or None, ville or None, type or None)


@router.delete("/services/decisions/{decision_id}", summary="Cancels a service decision and restores the place.")
def delete_service_decision(decision_id: int, tab: str = "liens", service: str | None = None,
                            ville: str | None = None, type: str | None = None, _admin=Depends(require_admin)):
    try:
        poi_review_service.cancel_decision(decision_id)
        return poi_review_service.get_reviews(tab, service or None, ville or None, type or None)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))


# Onglet « Modifier » : corriger n'importe quel lieu ou spot, même sans signal (poi_edit_service, spot_edit_service).
# Chaque réponse renvoie la recherche telle qu'elle était, avec la correction appliquée.

def _edit_services(data: dict) -> dict:
    return poi_edit_service.search(data.get("ville"), data.get("service") or None, data.get("type") or None,
                                   data.get("nom") or None)


def _edit_spots(data: dict) -> dict:
    return spot_edit_service.search(data.get("ville"), data.get("nom") or None)


@router.get("/edit/services", summary="Finds any service place to correct, signal or not.")
def get_edit_services(ville: int | None = None, service: str | None = None, type: str | None = None,
                      nom: str | None = None, _admin=Depends(require_admin)):
    try:
        return _edit_services({"ville": ville, "service": service, "type": type, "nom": nom})
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))


@router.post("/edit/services/decisions", summary="Applies and records a correction on one place.")
def post_edit_service(data: dict = Body(...), admin=Depends(require_admin)):
    """data = {"poi_id": 32498, "action": "autre_nom", "nom": "Cave de Keruzas", "url": None, "mois": [], "note": "",
    "ville": 12, "service": "commerce", "type": "", "nom_recherche": "keruzas"}"""
    if not isinstance(data.get("poi_id"), int):
        raise HTTPException(status_code=422, detail="Lieu invalide")
    try:
        poi_edit_service.decide(data["poi_id"], data.get("action"), data.get("note") or "", admin["username"],
                                data.get("mois"), data.get("url"), data.get("nom"))
        return _edit_services({**data, "nom": data.get("nom_recherche")})
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))


@router.delete("/edit/services/decisions/{decision_id}", summary="Cancels a correction and restores the place.")
def delete_edit_service(decision_id: int, ville: int | None = None, service: str | None = None,
                        type: str | None = None, nom: str | None = None, _admin=Depends(require_admin)):
    try:
        poi_review_service.cancel_decision(decision_id)
        return _edit_services({"ville": ville, "service": service, "type": type, "nom": nom})
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))


@router.get("/edit/spots", summary="Finds any spot to correct, verification or not.")
def get_edit_spots(ville: int | None = None, nom: str | None = None, _admin=Depends(require_admin)):
    try:
        return _edit_spots({"ville": ville, "nom": nom})
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))


@router.post("/edit/spots/decisions", summary="Removes or keeps a spot, with its corrected text.")
def post_edit_spot(data: dict = Body(...), admin=Depends(require_admin)):
    """data = {"spot_id": 1368, "decision": "retirer", "note": "", "a_savoir": None, "ville": 12, "nom": ""}"""
    if data.get("decision") not in supervision_service.DECISIONS or not isinstance(data.get("spot_id"), int):
        raise HTTPException(status_code=422, detail="Décision invalide")
    a_savoir = data.get("a_savoir")
    if a_savoir is not None and not isinstance(a_savoir, str):
        raise HTTPException(status_code=422, detail="Texte invalide")
    try:
        supervision_service.decide(data["spot_id"], data["decision"], data.get("note") or "", admin["username"], a_savoir)
        return _edit_spots(data)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))


@router.put("/edit/spots/decisions/{decision_id}", summary="Corrects the text kept by a spot decision.")
def put_edit_spot(decision_id: int, data: dict = Body(...), _admin=Depends(require_admin)):
    if not isinstance(data.get("a_savoir"), str):
        raise HTTPException(status_code=422, detail="Texte invalide")
    supervision_service.correct_a_savoir(decision_id, data["a_savoir"])
    return _edit_spots(data)


@router.delete("/edit/spots/decisions/{decision_id}", summary="Cancels a spot decision; it stays recorded.")
def delete_edit_spot(decision_id: int, ville: int | None = None, nom: str | None = None, _admin=Depends(require_admin)):
    supervision_service.cancel_decision(decision_id)
    return _edit_spots({"ville": ville, "nom": nom})


@router.post("/edit/spots/openings", summary="Sets the opening dates of a spot.")
def post_edit_opening(data: dict = Body(...), admin=Depends(require_admin)):
    """data = {"spot_id": 1368, "statut": "periode", "debut": "01/04", "fin": "31/10", "convention": False, "note": ""}"""
    if not isinstance(data.get("spot_id"), int):
        raise HTTPException(status_code=422, detail="Spot invalide")
    try:
        spot_edit_service.decide_opening(data["spot_id"], data.get("statut"), data.get("debut"), data.get("fin"),
                                         data.get("note") or "", admin["username"], bool(data.get("convention")))
        return _edit_spots(data)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))


@router.delete("/edit/spots/openings/{decision_id}", summary="Cancels an opening decision and restores the previous values.")
def delete_edit_opening(decision_id: int, ville: int | None = None, nom: str | None = None,
                        _admin=Depends(require_admin)):
    supervision_service.cancel_opening_decision(decision_id)
    return _edit_spots({"ville": ville, "nom": nom})
