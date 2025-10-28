from fastapi import APIRouter, Query, Body
from services.plan_service import insert_or_update_plan

router = APIRouter()

@router.get("/spots")
def get_spots(city_id: int = Query(...), hike_id: int = Query(...)):
    # Retourne les spots
    return [{"id": 100, "type": "Camping", "nom": "Camping de la Plage"}]

@router.put("/update_plan/{plan_id}")
def update_plan(plan_id: int, data: dict = Body(...)):
    plan_id = insert_or_update_plan(plan_id, data)
    return {"status": "updated", "plan_id": plan_id, "recap": data}
