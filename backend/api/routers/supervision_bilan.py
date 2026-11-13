from fastapi import APIRouter, Depends

from api.dependencies import require_admin
from services import supervision_summary_service

router = APIRouter()


@router.get("/bilan", summary="How many decisions are left, queue by queue.")
def get_summary(_admin=Depends(require_admin)):
    return supervision_summary_service.get_summary()
