from fastapi import APIRouter, Query
from utils.db_utils import MySQLUtils

router = APIRouter()

@router.get("/", summary="Retrieve the trip plan details by plan ID.")
def get_plan(plan_id: int = Query(...)):
    cnx = MySQLUtils.connect()
    cursor = cnx.cursor(dictionary=True)
    cursor.execute("SELECT * FROM plans WHERE plan_id = %s", (plan_id,))
    plan = cursor.fetchone()
    cursor.close()
    MySQLUtils.disconnect(cnx)
    return plan
