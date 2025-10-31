from fastapi import APIRouter, Query, Body
from services.plan_service import insert_or_update_plan

router = APIRouter()

@router.get("/hikes", summary="Returns the hikes for a given city.")
def get_hikes(city_id: int = Query(...)):
    # Retourne les randonnées pour la ville
    return [{"id": 10, "nom": "Sentier des Douaniers"}]

@router.put("/update_plan/{plan_id}", summary="Update an existing trip plan with new data.")
def update_plan(plan_id: int, data: dict = Body(...)):
    plan_id = insert_or_update_plan(plan_id, data)
    return {"status": "updated", "plan_id": plan_id, "recap": data}
