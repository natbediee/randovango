"""
Les relectures de la supervision : ce qui reste à trancher (carte #186, section « Relectures » de /docs).

Une route par relecture (spots, services, bilan), en lecture seule : elles ne changent rien en base. Les gestes
(décider, annuler, corriger) sont dans les routes des décisions. Toutes sont réservées aux admins (require_admin).
"""
from fastapi import APIRouter, Depends

from api.dependencies import require_admin
from services.supervision import summary

router = APIRouter()


@router.get("/reviews/summary", summary="How many decisions are left, queue by queue.")
def get_summary(_admin=Depends(require_admin)):
    """Le bilan : combien il reste à trancher, file par file, et les notes données aux propositions des agents."""
    return summary.get_summary()
