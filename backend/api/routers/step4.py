from fastapi import APIRouter, Query, Body
from services.plan_service import insert_or_update_plan

router = APIRouter()

@router.get("/services",summary="Returns the services for a given city, hike, and spot.")
def get_services(city_id: int = Query(...), hike_id: int = Query(...), spot_id: int = Query(...)):
    # Retourne les services disponibles
    return [{"id": 200, "categorie": "Ravitaillement", "nom": "Super U"}]

@router.put("/update_plan/{plan_id}",summary="Update an existing trip plan with new data.")
def update_plan(plan_id: int, data: dict = Body(...)):
    plan_id = insert_or_update_plan(plan_id, data)
    return {"status": "updated", "plan_id": plan_id, "recap": data}
