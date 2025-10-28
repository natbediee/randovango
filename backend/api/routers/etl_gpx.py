from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from pathlib import Path
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from utils.service_utils import ServiceUtil
from api.models.etl_gpx import GPXUploadResponse

router = APIRouter()

ALLOWED_EXT = {"gpx"}

def get_data_gpx_dir():
    # Récupère le chemin DATA_GPX depuis .env ou valeur par défaut
    return Path(ServiceUtil.get_env('DATA_GPX', 'data/in/gpx')).resolve()

# Auth dépendance
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")
SECRET_KEY = ServiceUtil.get_env("JWT_SECRET", "dev-secret")
ALGORITHM = "HS256"

def get_current_user(token: str = Depends(oauth2_scheme)):
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
    # Vérification extension
    ext = file.filename.split(".")[-1].lower()
    if ext not in ALLOWED_EXT:
        return GPXUploadResponse(success=False, message=f"Extension non autorisée: {ext}")
    # Sauvegarde du fichier dans le dossier DATA_GPX
    data_gpx_dir = get_data_gpx_dir()
    data_gpx_dir.mkdir(parents=True, exist_ok=True)
    dest_path = data_gpx_dir / file.filename
    with open(dest_path, "wb") as f:
        f.write(await file.read())
    # Lancer le pipeline ETL (traitement synchrone)
    try:
        from etl.etl_pipeline import main as run_etl_pipeline
        city = run_etl_pipeline()
        if city:
            msg = f"Nouveau tracé sur {city} (fichier {file.filename} importé et pipeline lancé)."
        else:
            msg = f"Fichier {file.filename} importé et pipeline lancé."
        return GPXUploadResponse(success=True, message=msg, ville=city)
    except Exception as e:
        return GPXUploadResponse(success=False, message=f"Erreur ETL: {e}")
