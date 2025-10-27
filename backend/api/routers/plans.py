"""
Router pour la gestion des plans (trip_plans, trip_days, trip_day_pois)
"""
from fastapi import APIRouter
from typing import List
from api.models.plans import PlanCreate, PlanUpdate, PlanListItem, PlanDetail, PlanResponse

router = APIRouter(prefix="/plans", tags=["plans"])

@router.post("/", response_model=PlanResponse)
def create_plan(plan: PlanCreate):
    """Créer un nouveau plan (trip_plans + jours + POIs)"""
    # TODO: Insérer dans trip_plans, trip_days, trip_day_pois
    # Retourner l'id du plan créé
    raise NotImplementedError

@router.get("/mes", response_model=List[PlanListItem])
def list_my_plans():
    """Lister les plans de l'utilisateur (auth ou token)"""
    # TODO: Filtrer par user_id ou user_token
    raise NotImplementedError

@router.get("/{plan_id}", response_model=PlanDetail)
def get_plan(plan_id: int):
    """Obtenir le détail d'un plan"""
    # TODO: Charger trip_plans, trip_days, trip_day_pois
    raise NotImplementedError

@router.put("/{plan_id}", response_model=PlanResponse)
def update_plan(plan_id: int, plan: PlanUpdate):
    """Mettre à jour un plan existant"""
    # TODO: Mettre à jour trip_plans, trip_days, trip_day_pois
    raise NotImplementedError

@router.delete("/{plan_id}", response_model=PlanResponse)
def delete_plan(plan_id: int):
    """Supprimer un plan"""
    # TODO: Supprimer trip_plans (CASCADE sur trip_days, trip_day_pois)
    raise NotImplementedError

@router.get("/{plan_id}/export")
def export_plan(plan_id: int):
    """Exporter un plan (PDF, CSV, etc.)"""
    # TODO: Générer un export du plan
    raise NotImplementedError
