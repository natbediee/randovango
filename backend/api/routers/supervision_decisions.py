"""
Les décisions de la supervision : décider, corriger, annuler (carte #186, section « Décisions » de /docs).

Un seul chemin par geste, quel que soit ce qui est décidé (spot, ouverture, service) : le type est lu dans la
décision, ou donné dans le corps de la demande. Une route de décision répond par la décision elle-même, pas par la
page : chaque page recharge ensuite sa liste par sa route de lecture (relecture ou recherche), avec ses filtres.
Toutes sont réservées aux admins (require_admin) ; les règles communes sont dans services/supervision/decisions.py.
"""
from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import require_admin
from services.supervision import decisions

router = APIRouter()


@router.delete("/decisions/{decision_id}", summary="Cancels any decision (spot, opening, service); it stays recorded.")
def delete_decision(decision_id: int, _admin=Depends(require_admin)):
    """
    Annule une décision, quelle que soit la page d'où vient le clic : ce qu'elle avait changé revient comme avant, et
    elle reste en base, marquée annulée. Une décision inconnue ou déjà annulée (double clic) est refusée (422).
    Répond par la décision annulée : son numéro, ce qu'elle visait (objet_type, objet_id).
    """
    try:
        return decisions.cancel_decision(decision_id)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
