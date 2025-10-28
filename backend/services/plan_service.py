from utils.mysql_utils import MySQLUtils

def insert_or_update_plan(plan_id, data):
    cnx = MySQLUtils.connect()
    cursor = cnx.cursor()
    city_id = data.get("city_id")
    hike_id = data.get("hike_id")
    spot_id = data.get("spot_id")
    services = data.get("services")  # Peut être une liste ou un JSON

    if plan_id is None:
        # Création d'un nouveau plan
        cursor.execute(
            """
            INSERT INTO plans (city_id, hike_id, spot_id, services)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (city_id, hike_id, spot_id, str(services))
        )
        plan_id = cursor.lastrowid
    else:
        # Mise à jour d'un plan existant
        cursor.execute(
            """
            UPDATE plans SET city_id=%s, hike_id=%s, spot_id=%s, services=%
            WHERE plan_id=%s
            """,
            (city_id, hike_id, spot_id, str(services), plan_id)
        )
    cnx.commit()
    cursor.close()
    MySQLUtils.disconnect(cnx)
    return plan_id
