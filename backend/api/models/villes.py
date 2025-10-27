"""
Modèles Pydantic pour les villes et la météo
"""
from pydantic import BaseModel
from typing import List, Optional
from datetime import date

class VilleStats(BaseModel):
    """Statistiques d'une ville"""
    randonnees: int = 0
    spots: int = 0
    poi: int = 0

class MeteoForecast(BaseModel):
    """Prévision météo pour un jour"""
    date: date
    temp_max: float
    temp_min: float
    weather_code: int
    picto: str  # Nom du fichier pictogramme (ex: "cloudy.svg")
    precipitation_sum: Optional[float] = 0.0
    wind_speed_max: Optional[float] = 0.0

class VilleList(BaseModel):
    """Liste des villes disponibles"""
    id: int
    name: str
    department: Optional[str] = None
    region: Optional[str] = None
    latitude: float
    longitude: float
    country: Optional[str] = None
    stats: VilleStats
    meteo: Optional[List[MeteoForecast]] = []