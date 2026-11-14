"""
Les relectures de la supervision : ce qui reste à trancher (carte #186, section « Relectures » de /docs).

Une route par relecture (spots, services, bilan), en lecture seule : elles ne changent rien en base. Les gestes
(décider, annuler, corriger) sont dans les routes des décisions. Toutes sont réservées aux admins (require_admin).
"""
from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import require_admin
from services.supervision import services_edit, services_review, spots_review, summary

router = APIRouter()


@router.get("/reviews/spots", summary="Spots the agents propose to remove, and the latest decisions.")
def get_spot_reviews(_admin=Depends(require_admin)):
    """Les spots que l'agent propose de retirer, avec ses preuves, les dernières décisions et les ouvertures décidées."""
    return spot_reviews()


def spot_reviews() -> dict:
    """Ce que montre la page Spots : aussi la réponse des routes de décision sur un spot, tant qu'elles la renvoient."""
    return spots_review.get_reviews()


@router.get("/reviews/services", summary="Service checks awaiting a human decision, one queue at a time.")
def get_service_reviews(file: str = "liens", service: str | None = None, ville: str | None = None,
                        type: str | None = None, commune: str | None = None, _admin=Depends(require_admin)):
    """
    Une file des services à relire (file : liens, fermetures, saison, doublons, confirmer, ou « tous »), avec les
    filtres de la page : catégorie (service), sous-catégorie (type), ville de l'appli (ville) ou commune d'adresse
    qui n'en est pas une (commune). Une file inconnue est refusée (422).
    """
    try:
        return service_reviews(file, service or None, ville or None, type or None, commune or None)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))


def service_reviews(file: str, service: str | None = None, city: str | None = None, kind: str | None = None,
                    town: str | None = None) -> dict:
    """
    Une file de relecture des services, chaque lieu avec sa fiche complète (services_edit.attach_sheets) : ce que
    montre la page Services, et la réponse des routes de décision sur un service tant qu'elles la renvoient.
    """
    return services_edit.attach_sheets(services_review.get_reviews(file, service, city, kind, town))


@router.get("/reviews/summary", summary="How many decisions are left, queue by queue.")
def get_summary(_admin=Depends(require_admin)):
    """Le bilan : combien il reste à trancher, file par file, et les notes données aux propositions des agents."""
    return summary.get_summary()
