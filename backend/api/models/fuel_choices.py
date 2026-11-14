"""
Modèle Pydantic du carburant choisi dans l'onglet Carburant de l'étape 4 (carte #188).
"""
from typing import Optional

from pydantic import BaseModel


class FuelChoice(BaseModel):
    """Le carburant choisi : sa clé (« Gazole », « E10 »…), ou None pour « Tout »."""
    fuel: Optional[str] = None
