"""
Modèles Pydantic pour les villes et la météo
"""
from pydantic import BaseModel
from typing import List, Optional
from datetime import date

class CityStats(BaseModel):
    """Statistiques d'une ville"""
    hikes: int = 0
    spots: int = 0
    poi: int = 0

class CityStatsLabels(BaseModel):
    """Libellés prêts à afficher des statistiques ("12 randonnées", ...)"""
    hikes: str
    spots: str
    poi: str

class WeatherAdvice(BaseModel):
    """Conseil de randonnée affiché sous la carte météo"""
    icon: str  # Classe d'icône Font Awesome (ex: "fa-check-circle")
    text: str

class MeteoForecast(BaseModel):
    """Prévision météo pour un jour"""
    date: date
    temp_max: float
    temp_min: float
    weather_code: int
    picto: str  # Nom du fichier pictogramme (ex: "cloud")
    precipitation_sum: Optional[float] = 0.0
    wind_speed_max: Optional[float] = 0.0
    # Champs prêts à afficher, calculés par display_utils.enrich_meteo_forecasts.
    # Ils doivent être déclarés ici : pydantic retire silencieusement de la
    # réponse tout champ absent du response_model.
    day_label: Optional[str] = None
    css: Optional[str] = None
    advice: Optional[WeatherAdvice] = None
    temp_max_label: Optional[str] = None
    temp_min_label: Optional[str] = None
    precipitation_label: Optional[str] = None
    wind_label: Optional[str] = None

class CityList(BaseModel):
    """Liste des villes disponibles"""
    id: int
    name: str
    department: Optional[str] = None
    region: Optional[str] = None
    latitude: float
    longitude: float
    country: Optional[str] = None
    stats: CityStats
    stats_labels: Optional[CityStatsLabels] = None
    meteo: Optional[List[MeteoForecast]] = []