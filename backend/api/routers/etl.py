from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from pathlib import Path
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from utils.service_utils import ServiceUtil
from api.models.etl import GPXUploadResponse
from services.authentification import get_roles_for_user

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

@router.post("/upload_gpx", summary="Uploader un fichier GPX et lancer l'ETL", response_model=GPXUploadResponse)
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
        from etl.etl_pipeline import main as run_etl_pipeline
        city = run_etl_pipeline(user_role=user_role)
        # Si city est une liste, on ne retourne que la première (pour compatibilité front)
        if isinstance(city, list):
            city = city[0] if city else None
        if city:
            msg = f"Nouveau tracé sur {city} (fichier {file.filename})."
        else:
            msg = f"Fichier {file.filename} importé."
        return GPXUploadResponse(success=True, message=msg, city=city, role=user_role)
    except Exception as e:
        return GPXUploadResponse(success=False, message=f"Erreur ETL: {e}", role=user_role)
