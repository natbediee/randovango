"""
Lecture et écriture des plans de voyage (trip_plans, trip_days, trip_day_pois).

Un plan appartient SOIT à un compte (trip_plans.user_id), SOIT à un invité (trip_plans.user_token,
l'identifiant invité de son jeton, avec user_id = 0). Le propriétaire est toujours pris dans le
jeton du cookie, jamais dans ce qu'envoie le navigateur (carte #104).
"""
from utils.db_utils import MySQLUtils

# user_id d'un plan d'invité : 0, qui n'est l'identifiant d'aucun compte (les comptes commencent à 1).
GUEST_USER_ID = 0


def owner_columns(traveller: dict) -> tuple:
    """Les colonnes (user_id, user_token) d'un nouveau plan, d'après le voyageur du jeton."""
    if traveller["user_id"] is not None:
        return traveller["user_id"], None
    return GUEST_USER_ID, traveller["guest_id"]


def get_plan_owner(plan_id: int) -> dict | None:
    """Le propriétaire d'un plan : {"user_id", "user_token"}, ou None si le plan n'existe pas."""
    cnx = MySQLUtils.connect()
    cursor = cnx.cursor(dictionary=True)
    try:
        cursor.execute("SELECT user_id, user_token FROM trip_plans WHERE id = %s", (plan_id,))
        return cursor.fetchone()
    finally:
        cursor.close()
        MySQLUtils.disconnect(cnx)



def insert_or_update_plan(plan_id, data):
    """
    Met à jour un jour de plan existant (créé à l'étape 1 dans trip_plans/trip_days).

    data peut contenir :
    - hike_id (int ou None) : étape 2 – randonnée choisie, None pour « sans rando »
    - spot_id (int ou None) : étape 3 – spot de nuit choisi (doit exister dans spots),
                              None pour « autre hébergement »
    - services (list[int])  : étape 4 – IDs des POI sélectionnés → trip_day_pois
    - day_number (int)      : numéro du jour concerné (défaut : 1)

    Une clé absente laisse la colonne telle quelle ; une clé présente à None la vide
    (carte #231 : un spot remplacé par « autre hébergement » restait en base).
    """
    # « with » : la connexion se ferme à la sortie du bloc, même en cas d'erreur (issue #206).
    with MySQLUtils.open_cursor() as (cnx, cursor):
        day_number = data.get("day_number", 1)
        hike_id = data.get("hike_id")
        spot_id = data.get("spot_id")
        services = data.get("services")

        # Récupérer le trip_day correspondant au plan et au jour
        cursor.execute(
            "SELECT id FROM trip_days WHERE trip_plan_id = %s AND day_number = %s",
            (plan_id, day_number)
        )
        row = cursor.fetchone()

        if row is None:
            # Créer le trip_day s'il n'existe pas encore
            cursor.execute(
                "INSERT INTO trip_days (trip_plan_id, day_number, hike_id, spot_id) VALUES (%s, %s, %s, %s)",
                (plan_id, day_number, hike_id, spot_id)
            )
            trip_day_id = cursor.lastrowid
        else:
            trip_day_id = row[0]
            # On teste la présence de la clé, pas sa valeur : chaque étape n'envoie que
            # son propre choix, et None veut dire « sans rando » ou « autre hébergement ».
            if "hike_id" in data:
                cursor.execute(
                    "UPDATE trip_days SET hike_id = %s WHERE id = %s",
                    (hike_id, trip_day_id)
                )
            if "spot_id" in data:
                # spot_id FK → spots(id) : le spot doit exister dans la table spots (None est permis)
                cursor.execute(
                    "UPDATE trip_days SET spot_id = %s WHERE id = %s",
                    (spot_id, trip_day_id)
                )

        # Services / POI sélectionnés à l'étape 4 → trip_day_pois
        if services is not None:
            cursor.execute("DELETE FROM trip_day_pois WHERE trip_day_id = %s", (trip_day_id,))
            for poi_id in services:
                cursor.execute(
                    "INSERT IGNORE INTO trip_day_pois (trip_day_id, poi_id) VALUES (%s, %s)",
                    (trip_day_id, int(poi_id))
                )

        cnx.commit()
    return plan_id


def set_day_city(plan_id, day_number, city_id):
    """
    Fixe la ville d'un jour donné (l'utilisateur peut changer de ville entre deux
    jours d'un même séjour). Appelé à chaque transition de jour depuis /results,
    que l'utilisateur reste dans la même ville ou en choisisse une autre.
    """
    # « with » : la connexion se ferme à la sortie du bloc, même en cas d'erreur (issue #206).
    with MySQLUtils.open_cursor() as (cnx, cursor):
        cursor.execute(
            "UPDATE trip_days SET city_id = %s WHERE trip_plan_id = %s AND day_number = %s",
            (city_id, plan_id, day_number)
        )
        cnx.commit()
    return plan_id
