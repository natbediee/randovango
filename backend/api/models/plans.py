"""
Modèles Pydantic pour les plans de randonnée
"""
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, date

class TripDayPOI(BaseModel):
    poi_id: int

class TripDay(BaseModel):
    day_number: int
    hike_id: Optional[int] = None
    spot_id: Optional[int] = None
    pois: Optional[List[TripDayPOI]] = []

class PlanCreate(BaseModel):
    """Création d'un nouveau plan (trip_plans + jours)"""
    start_date: date
    duration_days: int
    city_id: int
    user_token: Optional[str] = None
    user_id: Optional[int] = None
    days: List[TripDay]

class PlanUpdate(BaseModel):
    """Mise à jour d'un plan existant (jours, randos, spots, POIs)"""
    start_date: Optional[date] = None
    duration_days: Optional[int] = None
    city_id: Optional[int] = None
    days: Optional[List[TripDay]] = None

class PlanListItem(BaseModel):
    """Élément de liste de plan (résumé)"""
    id: int
    start_date: date
    duration_days: int
    city_id: int
    created_at: datetime

class PlanDetail(BaseModel):
    """Détails complets d'un plan (trip_plans + jours + POIs)"""
    id: int
    start_date: date
    duration_days: int
    city_id: int
    user_token: Optional[str] = None
    user_id: Optional[int] = None
    created_at: datetime
    days: List[TripDay]

class PlanResponse(BaseModel):
    """Réponse après création/mise à jour d'un plan"""
    plan_id: int
    created_at: Optional[datetime] = None
