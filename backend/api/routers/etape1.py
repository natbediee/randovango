from fastapi import APIRouter, Body, HTTPException, Query
from backend.services.plan_service import insert_or_update_plan
from backend.utils.mysql_utils import MySQLUtils
from backend.etl.etl_meteo import run_meteo_etl

router = APIRouter()

@router.get("/villes")
def get_villes():
    cnx = MySQLUtils.connect()
    cursor = cnx.cursor(dictionary=True)
    cursor.execute("SELECT id, nom FROM cities ORDER BY nom ASC")
    villes = cursor.fetchall()
    cursor.close()
    MySQLUtils.disconnect(cnx)
    return villes

@router.post("/meteo_etl")
def meteo_etl(data: dict = Body(...)):
    ville_id = data.get("ville_id")
    result = run_meteo_etl(ville_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    if "warning" in result:
        return {"status": "warning", "message": result["warning"]}
    return {"status": "ok", "data": result}

@router.get("/meteo")
def get_meteo(ville_id: int = Query(...)):
    cnx = MySQLUtils.connect()
    cursor = cnx.cursor(dictionary=True)
    cursor.execute("SELECT nom FROM cities WHERE id = %s", (ville_id,))
    row = cursor.fetchone()
    if not row:
        cursor.close()
        MySQLUtils.disconnect(cnx)
        raise HTTPException(status_code=404, detail="Ville inconnue")
    city_name = row['nom']
    cursor.execute("SELECT * FROM meteo WHERE city = %s", (city_name,))
    meteo = cursor.fetchall()
    cursor.close()
    MySQLUtils.disconnect(cnx)
    return {"city": city_name, "meteo": meteo}

# A DEVELOPPER
@router.post("/create_plan")
def create_plan(data: dict = Body(...)):
    plan_id = insert_or_update_plan(None, data)
    return {"status": "created", "plan_id": plan_id, "recap": data}

