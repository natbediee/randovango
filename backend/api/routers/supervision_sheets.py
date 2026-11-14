"""
La fiche d'un service dans la supervision : tout ce que voit le voyageur à l'étape 4, à corriger d'un coup
(carte #186, section « Services » de /docs). La page la montre dans l'onglet « Modifier » et sur les cartes de
relecture (supervision_fiche.js).

Réservée aux admins (require_admin).
"""
from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import require_admin
from services.supervision import services_edit

router = APIRouter()


@router.get("/services/{poi_id}", summary="The full sheet of one service, as the traveller sees it.")
def get_service_sheet(poi_id: int, _admin=Depends(require_admin)):
    """La fiche complète d'un service ; un service qui n'existe pas répond 404."""
    try:
        return services_edit.get_sheet(poi_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error))
