"""
Les décisions de la supervision : décider, corriger, annuler (carte #186, section « Décisions » de /docs).

Un seul chemin par geste, quel que soit ce qui est décidé (spot, ouverture, service) : le type est lu dans la
décision, ou donné dans le corps de la demande. Une route de décision répond par la décision elle-même, pas par la
page : chaque page recharge ensuite sa liste par sa route de lecture (relecture ou recherche), avec ses filtres.
Toutes sont réservées aux admins (require_admin) ; les règles communes sont dans services/supervision/decisions.py.
"""
from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import require_admin
from api.models.supervision import Decision, OpeningDecision, ServiceDecision, SpotDecision, TextCorrection
from services.supervision import decisions, rating, services_edit, services_review, spots_edit, spots_review

router = APIRouter()


def checked_rating(pertinence: str | None, raison: str | None) -> tuple:
    """
    La note facultative de la proposition de l'agent (#201) : (pertinence, raison), None pour ce qui n'est pas noté
    (une liste laissée vide sur la page envoie une chaîne vide). Une valeur que rating ne connaît pas est refusée (400) :
    rien n'est enregistré.
    """
    pertinence, raison = pertinence or None, raison or None
    try:
        rating.check_rating(pertinence, raison)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    return pertinence, raison


def decide_spot(body: SpotDecision, decided_by: str) -> None:
    """Garde ou retire un spot, avec son texte corrigé et la note de la proposition de l'agent."""
    pertinence, raison = checked_rating(body.pertinence, body.raison)
    spots_review.decide(body.objet_id, body.decision, body.note, decided_by, body.a_savoir, pertinence, raison)


def decide_opening(body: OpeningDecision, decided_by: str) -> None:
    """Enregistre les dates d'ouverture d'un spot."""
    spots_edit.decide_opening(body.objet_id, body.statut, body.debut, body.fin, body.note, decided_by, body.convention)


def decide_service(body: ServiceDecision, decided_by: str) -> None:
    """
    Décide sur un service. Depuis une file de relecture (body.file), la décision tranche aussi les signaux de la file
    (services_review) ; depuis Modifier, elle corrige le service, même sans signal (services_edit).
    """
    pertinence, raison = checked_rating(body.pertinence, body.raison)
    if pertinence and (len(body.objet_ids) > 1 or not body.file):
        # La note juge une proposition de l'agent : un lot de liens, ou une correction dans Modifier, n'en a pas.
        raise HTTPException(status_code=400, detail="Seule une décision sur une proposition de l'agent se note")
    if body.file:
        services_review.decide(body.file, body.objet_ids, body.decision, body.note, decided_by, body.mois, body.url,
                               body.nom, pertinence, raison)
        return
    if len(body.objet_ids) > 1:
        raise ValueError("Dans Modifier, on corrige un service à la fois")
    services_edit.decide(body.objet_ids[0], body.decision, body.note, decided_by, body.mois, body.url, body.nom)


@router.post("/decisions", summary="Records a decision on a spot, its opening dates, or a service.")
def post_decision(body: Decision, admin=Depends(require_admin)):
    """
    Une seule route pour décider, depuis Spots, Services ou Modifier : le champ « objet » dit sur quoi.
    {"objet": "spot", "objet_id": 1368, "decision": "garder", "note": "Vu sur Street View", "pertinence": "fausse",
     "raison": "preuve_faible"}
    {"objet": "ouverture", "objet_id": 1368, "statut": "periode", "debut": "01/04", "fin": "31/10", "convention": false}
    {"objet": "service", "objet_ids": [2686], "file": "fermetures", "decision": "retirer", "pertinence": "a_corriger",
     "raison": "nom_adresse"}
    {"objet": "service", "objet_ids": [32498], "decision": "autre_nom", "nom": "Cave de Keruzas"}   (depuis Modifier)
    Un spot ou un service inconnu, une action non permise, une date ou un lien mal tapé est refusé (422) avec le motif.
    Répond par la décision reçue ; la page recharge ensuite sa liste (plan de #186, 2.1).
    """
    try:
        if body.objet == "spot":
            decide_spot(body, admin["username"])
        elif body.objet == "ouverture":
            decide_opening(body, admin["username"])
        else:
            decide_service(body, admin["username"])
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    return body.model_dump()


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


@router.put("/decisions/{decision_id}", summary="Corrects the « À savoir » text kept by a spot decision.")
def put_decision(decision_id: int, body: TextCorrection, _admin=Depends(require_admin)):
    """
    Corrige le texte « À savoir » d'une décision sur un spot, sans refaire la décision. Un numéro qui n'est pas celui
    d'une décision de spot encore valable est refusé (422). Répond par la décision et son nouveau texte.
    """
    try:
        spots_review.correct_a_savoir(decision_id, body.a_savoir)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    return {"id": decision_id, "a_savoir": body.a_savoir}


@router.post("/decisions/{decision_id}/audit", summary="Marks a rule decision as checked by a human.")
def post_decision_audit(decision_id: int, _admin=Depends(require_admin)):
    """
    « C'est juste » sur une décision prise par la règle (contrôle au hasard de la page Services) : elle ne sera plus
    tirée au sort. Un numéro qui n'est pas celui d'une décision de la règle est refusé (422).
    """
    try:
        services_review.confirm_audit(decision_id)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    return {"id": decision_id}
