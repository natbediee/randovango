from utils.db_utils import MySQLUtils
from utils.mongo_utils import MongoUtils
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from pathlib import Path
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from utils.service_utils import ServiceUtil
from api.models.etl import GPXUploadResponse, GPXDeleteResponse
from etl.etl_pipeline import main as run_etl_pipeline
from services.authentification import get_roles_for_user, insert_auth_log

router = APIRouter()

ALLOWED_EXT = {"gpx"}
security = HTTPBearer()


# Auth dépendance
SECRET_KEY = ServiceUtil.get_env("JWT_SECRET", "dev-secret")
ALGORITHM = "HS256"

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: int = payload.get("user_id")
        username: str = payload.get("username")
        if user_id is None or username is None:
            raise HTTPException(status_code=401, detail="Token invalide")
        return {"user_id": user_id, "username": username}
    except JWTError:
        raise HTTPException(status_code=401, detail="Token invalide")

@router.post("/upload_gpx", summary="Upload a GPX file and launch the ETL pipeline (Admin and Contributor only)", response_model=GPXUploadResponse)
async def upload_gpx(
    file: UploadFile = File(..., description="Fichier GPX"),
    user=Depends(get_current_user)
):
    # Récupérer le rôle de l'utilisateur
    user_id = user["user_id"]
    roles = get_roles_for_user(user_id)
    user_role = "admin" if "admin" in roles else "user"
    # Vérification extension
    ext = file.filename.split(".")[-1].lower()
    if ext not in ALLOWED_EXT:
        return GPXUploadResponse(success=False, message=f"Extension non autorisée: {ext}")
    # Sauvegarde du fichier dans le dossier data (volume Docker)
    DATA = Path("/usr/src/data")
    DATA.mkdir(parents=True, exist_ok=True)
    dest_path = DATA / file.filename
    with open(dest_path, "wb") as f:
        f.write(await file.read())
    # Lancer le pipeline ETL (traitement synchrone)
    try:
        city = run_etl_pipeline(user_role=user_role)
        # Si city est une liste, on ne retourne que la première (pour compatibilité front)
        if isinstance(city, list):
            city = city[0] if city else None
        if city:
            msg = f"Nouveau tracé sur {city} (fichier {file.filename})."
        else:
            msg = f"Fichier {file.filename} importé."
        # Audit log - succès
        insert_auth_log(
            user_id=user_id,
            username=user["username"],
            action="upload_gpx",
            route="/api/etl/upload_gpx",
            status_code=200,
            token=None,
            filename=file.filename
        )
        return GPXUploadResponse(success=True, message=msg, city=city, role=user_role)
    except Exception as e:
        # Audit log - échec
        insert_auth_log(
            user_id=user_id,
            username=user["username"],
            action="upload_gpx_failed",
            route="/api/etl/upload_gpx",
            status_code=500,
            token=None,
            filename=file.filename
        )
        return GPXUploadResponse(success=False, message=f"Erreur ETL: {e}", role=user_role)

@router.delete("/delete_gpx/{filename}", summary="Delete a GPX file (Admin only)", response_model=GPXDeleteResponse)
async def delete_gpx(
    filename: str,
    user=Depends(get_current_user)
):
    """
    Supprime un fichier GPX du dossier data et la randonnée associée dans MySQL/MongoDB. Nécessite un rôle admin.
    """
    # Vérifier que l'utilisateur est admin
    user_id = user["user_id"]
    roles = get_roles_for_user(user_id)
    if "admin" not in roles:
        raise HTTPException(status_code=403, detail="Accès refusé : rôle admin requis")

    # Vérifier l'extension
    ext = filename.split(".")[-1].lower()
    if ext not in ALLOWED_EXT:
        return GPXDeleteResponse(success=False, message=f"Extension non autorisée: {ext}")

    # Suppression dans MySQL
    cnx = MySQLUtils.connect()
    cursor = cnx.cursor()
    cursor.execute("DELETE FROM hikes WHERE filename = %s", (filename,))
    mysql_deleted = cursor.rowcount
    cnx.commit()
    cursor.close()
    MySQLUtils.disconnect(cnx)

    # Suppression dans MongoDB
    MongoUtils.connect()
    collection = MongoUtils.get_collection("gpx_traces")
    result = collection.delete_many({"filename": filename})
    mongo_deleted = result.deleted_count
    MongoUtils.disconnect()

    # Audit log - succès
    insert_auth_log(
        user_id=user_id,
        username=user["username"],
        action="delete_gpx",
        route="/api/etl/delete_gpx",
        status_code=200,
        token=None,
        filename=filename
    )
    msg = f"Suppression en base : MySQL={mysql_deleted}, MongoDB={mongo_deleted}"
    return GPXDeleteResponse(success=True, message=msg, deleted_file=filename)