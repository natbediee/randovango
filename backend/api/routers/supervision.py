import logging

from fastapi import APIRouter, Body, Depends, HTTPException

from api.dependencies import require_admin
from services.supervision import decisions, rating, services_edit, services_review, spots_edit, spots_review

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/reviews", summary="Agents' proposals awaiting a human decision.")
def get_reviews(_admin=Depends(require_admin)):
    return spots_review.get_reviews()


def _rating(data: dict) -> tuple:
    """
    La note facultative de la proposition de l'agent (#201) : (pertinence, raison), None pour ce qui n'est pas noté.
    Une valeur que rating ne connaît pas est refusée (400) : rien n'est enregistré.
    """
    pertinence, raison = data.get("pertinence") or None, data.get("raison") or None
    try:
        rating.check_rating(pertinence, raison)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    return pertinence, raison


def _cancel(decision_id: int) -> None:
    """
    Annule une décision, quel que soit l'onglet d'où vient le clic : decisions.cancel_decision lit son type.
    Une décision inconnue ou déjà annulée (double clic) est refusée (422) : rien n'est changé.
    """
    try:
        decisions.cancel_decision(decision_id)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))


@router.post("/decisions", summary="Records a human decision on a proposal.")
def post_decision(data: dict = Body(...), admin=Depends(require_admin)):
    """
    data = {"objet_id": 1368, "decision": "garder", "note": "Vu sur Street View", "a_savoir": "...",
            "pertinence": "fausse", "raison": "preuve_faible"}
    "a_savoir" (facultatif) : le texte corrigé, une phrase par ligne ; absent, celui de l'agent reste.
    "pertinence" et "raison" (facultatives) : la note de la proposition de l'agent (rating).
    """
    if data.get("decision") not in spots_review.DECISIONS or not isinstance(data.get("objet_id"), int):
        raise HTTPException(status_code=422, detail="Décision invalide")
    pertinence, raison = _rating(data)
    spots_review.decide(data["objet_id"], data["decision"], data.get("note") or "", admin["username"],
                               data.get("a_savoir"), pertinence, raison)
    return spots_review.get_reviews()


@router.put("/decisions/{decision_id}", summary="Corrects the text kept by a decision.")
def put_decision(decision_id: int, data: dict = Body(...), _admin=Depends(require_admin)):
    """data = {"a_savoir": "..."} : une phrase par ligne, vide s'il n'y a plus rien à signaler."""
    if not isinstance(data.get("a_savoir"), str):
        raise HTTPException(status_code=422, detail="Texte invalide")
    spots_review.correct_a_savoir(decision_id, data["a_savoir"])
    return spots_review.get_reviews()


@router.delete("/decisions/{decision_id}", summary="Cancels a decision; it stays recorded.")
def delete_decision(decision_id: int, _admin=Depends(require_admin)):
    _cancel(decision_id)
    return spots_review.get_reviews()


@router.delete("/openings/{decision_id}", summary="Cancels an opening decision and restores the previous values.")
def delete_opening_decision(decision_id: int, _admin=Depends(require_admin)):
    _cancel(decision_id)
    return spots_review.get_reviews()


def _service_reviews(tab: str, service: str | None = None, city: str | None = None, kind: str | None = None,
                     town: str | None = None) -> dict:
    """
    Une file de relecture, chaque lieu avec sa fiche complète (services_edit.attach_sheets). town (paramètre
    « commune ») : une commune d'adresse qui n'est pas une ville de l'appli, comme dans « Modifier ».
    """
    return services_edit.attach_sheets(services_review.get_reviews(tab, service, city, kind, town))


@router.get("/services", summary="Service checks awaiting a human decision, one queue at a time.")
def get_service_reviews(tab: str = "liens", service: str | None = None, ville: str | None = None, type: str | None = None,
                        commune: str | None = None, _admin=Depends(require_admin)):
    try:
        return _service_reviews(tab, service or None, ville or None, type or None, commune or None)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))


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
    pertinence, raison = _rating(data)
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
    return _service_reviews(data.get("vue") or data["tab"], data.get("service") or None,
                            data.get("ville") or None, data.get("type") or None, data.get("commune") or None)


@router.post("/services/fiche", summary="Saves a corrected sheet from a review card.")
def post_service_sheet(data: dict = Body(...), admin=Depends(require_admin)):
    """
    data = {"tab": "confirmer", "poi_id": 12, "changes": {"texte": "...", "genre": "crêperie"}, "note": "",
    "vue": "tous", "service": "", "ville": "", "type": ""}. Corriger le champ que la file met en doute la tranche.
    """
    if not isinstance(data.get("poi_id"), int):
        raise HTTPException(status_code=422, detail="Lieu invalide")
    try:
        services_edit.decide_sheet(data["poi_id"], data.get("changes"), data.get("note") or "", admin["username"],
                                      data.get("tab"))
        return _service_reviews(data.get("vue") or data.get("tab"), data.get("service") or None,
                                data.get("ville") or None, data.get("type") or None, data.get("commune") or None)
    except ValueError as error:
        # Le motif du refus dans le journal : la page ne le montrait qu'en haut, hors de vue (8 novembre 2026).
        logger.warning("Fiche refusée (lieu %s, file %s, champs %s) : %s", data["poi_id"], data.get("tab"),
                       sorted(data.get("changes") or {}), error)
        raise HTTPException(status_code=422, detail=str(error))


@router.post("/services/audit/{decision_id}", summary="Marks a rule decision as checked by a human.")
def post_service_audit(decision_id: int, tab: str = "liens", service: str | None = None, ville: str | None = None,
                       type: str | None = None, commune: str | None = None, _admin=Depends(require_admin)):
    services_review.confirm_audit(decision_id)
    return _service_reviews(tab, service or None, ville or None, type or None, commune or None)


@router.delete("/services/decisions/{decision_id}", summary="Cancels a service decision and restores the place.")
def delete_service_decision(decision_id: int, tab: str = "liens", service: str | None = None,
                            ville: str | None = None, type: str | None = None, commune: str | None = None,
                            _admin=Depends(require_admin)):
    _cancel(decision_id)
    return _service_reviews(tab, service or None, ville or None, type or None, commune or None)


# Onglet « Modifier » : corriger n'importe quel lieu ou spot, même sans signal (services_edit, spots_edit).
# Chaque réponse renvoie la recherche telle qu'elle était, avec la correction appliquée.

def _edit_services(data: dict) -> dict:
    return services_edit.search(data.get("ville"), data.get("service") or None, data.get("type") or None,
                                   data.get("nom") or None, data.get("commune") or None)


def _edit_spots(data: dict) -> dict:
    return spots_edit.search(data.get("ville"), data.get("nom") or None)


@router.get("/edit/services", summary="Finds any service place to correct, signal or not.")
def get_edit_services(ville: int | None = None, service: str | None = None, type: str | None = None,
                      nom: str | None = None, commune: str | None = None, _admin=Depends(require_admin)):
    # commune : une commune des adresses qui n'est pas une ville de l'appli (« Guilvinec »), à la place de ville.
    try:
        return _edit_services({"ville": ville, "service": service, "type": type, "nom": nom, "commune": commune})
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))


@router.post("/edit/services/decisions", summary="Applies and records a correction on one place.")
def post_edit_service(data: dict = Body(...), admin=Depends(require_admin)):
    """data = {"poi_id": 32498, "action": "autre_nom", "nom": "Cave de Keruzas", "url": None, "mois": [], "note": "",
    "ville": 12, "commune": "", "service": "commerce", "type": "", "nom_recherche": "keruzas"}"""
    if not isinstance(data.get("poi_id"), int):
        raise HTTPException(status_code=422, detail="Lieu invalide")
    try:
        services_edit.decide(data["poi_id"], data.get("action"), data.get("note") or "", admin["username"],
                                data.get("mois"), data.get("url"), data.get("nom"))
        return _edit_services({**data, "nom": data.get("nom_recherche")})
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))


@router.get("/edit/services/fiche/{poi_id}", summary="The full sheet of one place, as the traveller sees it.")
def get_edit_sheet(poi_id: int, _admin=Depends(require_admin)):
    try:
        return services_edit.get_sheet(poi_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error))


@router.post("/edit/services/fiche", summary="Saves a corrected sheet: every field the traveller sees, at once.")
def post_edit_sheet(data: dict = Body(...), admin=Depends(require_admin)):
    """data = {"poi_id": 32498, "changes": {"name": "...", "texte": "...", "mois": [3, 4]}, "note": "", "ville": 12,
    "service": "commerce", "type": "", "nom_recherche": "keruzas"}. Renvoie la recherche et la fiche à jour."""
    if not isinstance(data.get("poi_id"), int):
        raise HTTPException(status_code=422, detail="Lieu invalide")
    try:
        services_edit.decide_sheet(data["poi_id"], data.get("changes"), data.get("note") or "", admin["username"])
        return {**_edit_services({**data, "nom": data.get("nom_recherche")}), "fiche": services_edit.get_sheet(data["poi_id"])}
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))


@router.delete("/edit/services/decisions/{decision_id}", summary="Cancels a correction and restores the place.")
def delete_edit_service(decision_id: int, ville: int | None = None, service: str | None = None,
                        type: str | None = None, nom: str | None = None, commune: str | None = None,
                        _admin=Depends(require_admin)):
    _cancel(decision_id)
    return _edit_services({"ville": ville, "service": service, "type": type, "nom": nom, "commune": commune})


@router.get("/edit/spots", summary="Finds any spot to correct, verification or not.")
def get_edit_spots(ville: int | None = None, nom: str | None = None, _admin=Depends(require_admin)):
    try:
        return _edit_spots({"ville": ville, "nom": nom})
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))


@router.post("/edit/spots/decisions", summary="Removes or keeps a spot, with its corrected text.")
def post_edit_spot(data: dict = Body(...), admin=Depends(require_admin)):
    """data = {"spot_id": 1368, "decision": "retirer", "note": "", "a_savoir": None, "ville": 12, "nom": ""}"""
    if data.get("decision") not in spots_review.DECISIONS or not isinstance(data.get("spot_id"), int):
        raise HTTPException(status_code=422, detail="Décision invalide")
    a_savoir = data.get("a_savoir")
    if a_savoir is not None and not isinstance(a_savoir, str):
        raise HTTPException(status_code=422, detail="Texte invalide")
    try:
        spots_review.decide(data["spot_id"], data["decision"], data.get("note") or "", admin["username"], a_savoir)
        return _edit_spots(data)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))


@router.put("/edit/spots/decisions/{decision_id}", summary="Corrects the text kept by a spot decision.")
def put_edit_spot(decision_id: int, data: dict = Body(...), _admin=Depends(require_admin)):
    if not isinstance(data.get("a_savoir"), str):
        raise HTTPException(status_code=422, detail="Texte invalide")
    spots_review.correct_a_savoir(decision_id, data["a_savoir"])
    return _edit_spots(data)


@router.delete("/edit/spots/decisions/{decision_id}", summary="Cancels a spot decision; it stays recorded.")
def delete_edit_spot(decision_id: int, ville: int | None = None, nom: str | None = None, _admin=Depends(require_admin)):
    _cancel(decision_id)
    return _edit_spots({"ville": ville, "nom": nom})


@router.post("/edit/spots/openings", summary="Sets the opening dates of a spot.")
def post_edit_opening(data: dict = Body(...), admin=Depends(require_admin)):
    """data = {"spot_id": 1368, "statut": "periode", "debut": "01/04", "fin": "31/10", "convention": False, "note": ""}"""
    if not isinstance(data.get("spot_id"), int):
        raise HTTPException(status_code=422, detail="Spot invalide")
    try:
        spots_edit.decide_opening(data["spot_id"], data.get("statut"), data.get("debut"), data.get("fin"),
                                         data.get("note") or "", admin["username"], bool(data.get("convention")))
        return _edit_spots(data)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))


@router.delete("/edit/spots/openings/{decision_id}", summary="Cancels an opening decision and restores the previous values.")
def delete_edit_opening(decision_id: int, ville: int | None = None, nom: str | None = None,
                        _admin=Depends(require_admin)):
    _cancel(decision_id)
    return _edit_spots({"ville": ville, "nom": nom})
