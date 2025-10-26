from fastapi import APIRouter, Query, Body
from backend.services.plan_service import insert_or_update_plan

router = APIRouter()

@router.get("/services")
def get_services(ville_id: int = Query(...), randonnee_id: int = Query(...), nuit_id: int = Query(...)):
    # Retourne les services disponibles
    return [{"id": 200, "categorie": "Ravitaillement", "nom": "Super U"}]

@router.put("/update_plan/{plan_id}")
def update_plan(plan_id: int, data: dict = Body(...)):
    plan_id = insert_or_update_plan(plan_id, data)
    return {"status": "updated", "plan_id": plan_id, "recap": data}
