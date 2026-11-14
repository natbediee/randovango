"""
La recherche de la supervision : retrouver n'importe quel service ou spot pour le corriger, même sans rien à relire
(onglet « Modifier », carte #186, section « Recherche » de /docs).

En lecture seule : ces routes ne changent rien en base. Elles sont réservées aux admins (require_admin).
"""
from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import require_admin
from services.supervision import services_edit, spots_edit

router = APIRouter()


@router.get("/search/services", summary="Finds any service place to correct, signal or not.")
def get_service_search(ville: int | None = None, service: str | None = None, type: str | None = None,
                       nom: str | None = None, commune: str | None = None, _admin=Depends(require_admin)):
    """
    Les services qui répondent aux filtres : ville de l'appli (ville) ou commune d'adresse qui n'en est pas une
    (commune, par exemple « Guilvinec »), catégorie (service), sous-catégorie (type), nom. Une recherche que le service
    refuse (par exemple sans ville ni nom) répond 422 avec son message.
    """
    try:
        return service_search({"ville": ville, "service": service, "type": type, "nom": nom, "commune": commune})
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))


@router.get("/search/spots", summary="Finds any spot to correct, verification or not.")
def get_spot_search(ville: int | None = None, nom: str | None = None, _admin=Depends(require_admin)):
    """Les spots d'une ville de l'appli (ville), ou ceux dont le nom contient « nom »."""
    try:
        return spot_search({"ville": ville, "nom": nom})
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))


def service_search(data: dict) -> dict:
    """
    La recherche de services de l'onglet « Modifier » : aussi la réponse des routes de correction, tant qu'elles
    renvoient la liste. Un filtre vide ("") compte comme absent.
    """
    return services_edit.search(data.get("ville"), data.get("service") or None, data.get("type") or None,
                                data.get("nom") or None, data.get("commune") or None)


def spot_search(data: dict) -> dict:
    """La recherche de spots de l'onglet « Modifier » : aussi la réponse des routes de correction d'un spot."""
    return spots_edit.search(data.get("ville"), data.get("nom") or None)
