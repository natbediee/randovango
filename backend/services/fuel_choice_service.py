"""
Le dernier carburant choisi par un voyageur dans l'onglet Carburant de l'étape 4 (carte #188), table fuel_choices.

Le choix est rattaché au voyageur comme ses voyages (services/plan_service.owner_columns) : un compte par son user_id,
un invité par son identifiant invité. Le jeton n'est jamais enregistré : celui d'un compte change à chaque connexion,
l'identité qu'il porte ne change pas, et le même carburant est retrouvé après une reconnexion.
"""
from datetime import datetime

from services.plan_service import owner_columns
from services.station_selection_service import FUEL_LABELS
from utils.db_utils import MySQLUtils

# Les carburants qu'on peut retenir : ceux des pastilles de prix (Gazole, E10, SP95, SP98, E85, GPLc).
# « Tout » s'écrit None (NULL en base).
ALLOWED_FUELS = set(FUEL_LABELS)


def owner_key(traveller: dict) -> tuple:
    """
    La clé (user_id, user_token) du voyageur dans fuel_choices. Pour un compte, owner_columns donne user_token = None :
    on le remplace par '' parce qu'une colonne de clé primaire ne peut pas être NULL.
    """
    user_id, user_token = owner_columns(traveller)
    return user_id, user_token or ""


def get_fuel_choice(traveller: dict) -> str | None:
    """
    Le carburant retenu pour ce voyageur : sa clé (« E10 »), ou None pour « Tout ». Un voyageur qui n'a encore rien
    choisi voit aussi « Tout » : toutes les stations et tous leurs prix (décision du 14 novembre 2026).
    """
    cnx = MySQLUtils.connect()
    cursor = cnx.cursor(dictionary=True)
    try:
        cursor.execute("SELECT fuel FROM fuel_choices WHERE user_id = %s AND user_token = %s", owner_key(traveller))
        row = cursor.fetchone()
        return row["fuel"] if row else None
    finally:
        cursor.close()
        MySQLUtils.disconnect(cnx)


def save_fuel_choice(traveller: dict, fuel: str | None) -> None:
    """
    Retient le carburant choisi (None pour « Tout »). La clé primaire garde une seule ligne par voyageur :
    un nouveau choix remplace l'ancien au lieu d'ajouter une ligne.
    """
    user_id, user_token = owner_key(traveller)
    cnx = MySQLUtils.connect()
    cursor = cnx.cursor()
    try:
        cursor.execute(
            """INSERT INTO fuel_choices (user_id, user_token, fuel, chosen_at) VALUES (%s, %s, %s, %s)
               ON DUPLICATE KEY UPDATE fuel = VALUES(fuel), chosen_at = VALUES(chosen_at)""",
            (user_id, user_token, fuel, datetime.now()))
        cnx.commit()
    finally:
        cursor.close()
        MySQLUtils.disconnect(cnx)
