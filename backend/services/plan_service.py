from utils.mysql_utils import MySQLUtils

# plans(plan_id INT PRIMARY KEY AUTO_INCREMENT, ville_id INT, randonnee_id INT, nuit_id INT, services JSON, etape INT)

def insert_or_update_plan(plan_id, data):
    cnx = MySQLUtils.connect()
    cursor = cnx.cursor()
    ville_id = data.get("ville_id")
    randonnee_id = data.get("randonnee_id")
    nuit_id = data.get("nuit_id")
    services = data.get("services")  # Peut être une liste ou un JSON
    etape = data.get("etape")

    if plan_id is None:
        # Création d'un nouveau plan
        cursor.execute(
            """
            INSERT INTO plans (ville_id, randonnee_id, nuit_id, services, etape)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (ville_id, randonnee_id, nuit_id, str(services), etape)
        )
        plan_id = cursor.lastrowid
    else:
        # Mise à jour d'un plan existant
        cursor.execute(
            """
            UPDATE plans SET ville_id=%s, randonnee_id=%s, nuit_id=%s, services=%s, etape=%s
            WHERE plan_id=%s
            """,
            (ville_id, randonnee_id, nuit_id, str(services), etape, plan_id)
        )
    cnx.commit()
    cursor.close()
    MySQLUtils.disconnect(cnx)
    return plan_id
