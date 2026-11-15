"""
La fiche d'un service dans la supervision : tout ce que voit le voyageur à l'étape 4, à lire et à corriger d'un coup
(carte #186, section « Services » de /docs). La page la montre dans l'onglet « Modifier » et sur les cartes de
relecture (supervision_fiche.js).

Réservée aux admins (require_admin).
"""
import logging

from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import require_admin
from api.models.supervision import SheetCorrection
from services.supervision import services_edit

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/services/{poi_id}", summary="The full sheet of one service, as the traveller sees it.")
def get_service_sheet(poi_id: int, _admin=Depends(require_admin)):
    """La fiche complète d'un service ; un service qui n'existe pas répond 404."""
    try:
        return services_edit.get_sheet(poi_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error))


@router.put("/services/{poi_id}", summary="Saves a corrected sheet: only the fields that changed.")
def put_service_sheet(poi_id: int, body: SheetCorrection, admin=Depends(require_admin)):
    """
    Enregistre la fiche corrigée d'un service, depuis Modifier ou depuis une carte de relecture (body.file).
    Répond par le service et les champs changés ; la page recharge ensuite sa liste (plan de #186, 2.1).
    Une correction refusée (lien invalide ou trop long, rien de changé, service inconnu) répond 422 avec le motif.
    """
    try:
        changed = services_edit.decide_sheet(poi_id, body.changes, body.note, admin["username"], body.file)
    except ValueError as error:
        # Le motif du refus dans le journal : la page ne le montrait qu'en haut, hors de vue (8 novembre 2026).
        logger.warning("Fiche refusée (service %s, file %s, champs %s) : %s", poi_id, body.file,
                       sorted(body.changes), error)
        raise HTTPException(status_code=422, detail=str(error))
    return {"poi_id": poi_id, "champs": changed}
