from fastapi import APIRouter, Depends

from api.dependencies import require_admin
from services.supervision import summary

router = APIRouter()


@router.get("/bilan", summary="How many decisions are left, queue by queue.")
def get_summary(_admin=Depends(require_admin)):
    return summary.get_summary()
