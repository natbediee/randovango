from fastapi import APIRouter, Query, Body
from backend.services.plan_service import insert_or_update_plan

router = APIRouter()

@router.get("/nuit")
def get_nuit(ville_id: int = Query(...), randonnee_id: int = Query(...)):
    # Retourne les spots
    return [{"id": 100, "type": "Camping", "nom": "Camping de la Plage"}]

@router.put("/update_plan/{plan_id}")
def update_plan(plan_id: int, data: dict = Body(...)):
    plan_id = insert_or_update_plan(plan_id, data)
    return {"status": "updated", "plan_id": plan_id, "recap": data}
