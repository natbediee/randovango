from utils.db_utils import MySQLUtils
from utils.mongo_utils import MongoUtils
from fastapi import APIRouter, UploadFile, File, Depends
from api.dependencies import get_current_user, require_admin
from api.models.etl import GPXUploadResponse, GPXDeleteResponse
from etl.etl_pipeline import main as run_etl_pipeline
from etl.extract.gpx import GPX_DIR
from services.authentification import get_roles_for_user, insert_auth_log

router = APIRouter()

ALLOWED_EXT = {"gpx"}


@router.post("/upload_gpx", summary="Upload a GPX file and launch the ETL pipeline (Admin and Contributor only)", response_model=GPXUploadResponse)
async def upload_gpx(
    file: UploadFile = File(..., description="Fichier GPX"),
    user=Depends(get_current_user)
):
    """
    Reçoit le GPX d'une rando depuis la page d'ajout, le charge en base et dit ce qui s'est vraiment passé :
    la ville du tracé chargé, ou le motif du refus (issue #266).
    """
    # Récupérer le rôle de l'utilisateur
    user_id = user["user_id"]
    roles = get_roles_for_user(user_id)
    user_role = "admin" if "admin" in roles else "user"
    # Vérification extension
    ext = file.filename.split(".")[-1].lower()
    if ext not in ALLOWED_EXT:
        return GPXUploadResponse(success=False, message=f"Extension non autorisée: {ext}")
    # Sauvegarde du fichier dans le dossier d'attente (volume Docker), celui que le pipeline lit.
    GPX_DIR.mkdir(parents=True, exist_ok=True)
    dest_path = GPX_DIR / file.filename
    with open(dest_path, "wb") as f:
        f.write(await file.read())
    # Lancer le pipeline ETL (traitement synchrone), puis retrouver le résultat du fichier envoyé.
    try:
        outcome = find_outcome(run_etl_pipeline(user_role=user_role), file.filename)
    except Exception as e:
        # Le fichier non chargé ne reste pas dans le dossier d'attente, sinon il repasserait au prochain envoi.
        dest_path.unlink(missing_ok=True)
        # Audit log - échec
        insert_auth_log(
            user_id=user_id,
            username=user["username"],
            action="upload_gpx_failed",
            route="/api/etl/upload_gpx",
            status_code=500,
            filename=file.filename
        )
        return GPXUploadResponse(success=False, message=f"Erreur ETL: {e}", role=user_role)

    if outcome["reason"]:
        # Refus : la page d'ajout montre le motif, pour que l'admin ou le contributeur sache quoi corriger (issue #266).
        insert_auth_log(
            user_id=user_id,
            username=user["username"],
            action="upload_gpx_refused",
            route="/api/etl/upload_gpx",
            status_code=200,
            filename=file.filename
        )
        return GPXUploadResponse(success=False, message=f"Fichier {file.filename} non chargé : {outcome['reason']}.",
                                 role=user_role)

    # Audit log - succès
    insert_auth_log(
        user_id=user_id,
        username=user["username"],
        action="upload_gpx",
        route="/api/etl/upload_gpx",
        status_code=200,
        filename=file.filename
    )
    city = outcome["city"]
    return GPXUploadResponse(success=True, message=f"Nouveau tracé sur {city} (fichier {file.filename}).",
                             city=city, role=user_role)


def find_outcome(outcomes, filename) -> dict:
    """
    Le résultat du fichier envoyé parmi ceux du dossier d'attente. S'il manque (fichier disparu entre l'écriture
    et la lecture), c'est un refus : jamais un succès annoncé pour un tracé que personne n'a chargé (issue #266).
    """
    for outcome in outcomes:
        if outcome["filename"] == filename:
            return outcome
    return {"filename": filename, "city": None, "reason": "le fichier n'a pas été traité"}


@router.delete("/delete_gpx/{filename}", summary="Delete a GPX file (Admin only)", response_model=GPXDeleteResponse)
async def delete_gpx(
    filename: str,
    user=Depends(require_admin)
):
    """
    Supprime un fichier GPX du dossier data et la randonnée associée dans MySQL/MongoDB. Nécessite un rôle admin :
    require_admin le vérifie avant la route (carte #106), comme pour la supervision, et la doc l'affiche.
    """
    user_id = user["user_id"]

    # Vérifier l'extension
    ext = filename.split(".")[-1].lower()
    if ext not in ALLOWED_EXT:
        return GPXDeleteResponse(success=False, message=f"Extension non autorisée: {ext}")

    # Suppression dans MySQL
    # « with » : la connexion se ferme à la sortie du bloc, même si la suppression échoue (issue #206).
    with MySQLUtils.open_cursor() as (cnx, cursor):
        cursor.execute("DELETE FROM hikes WHERE filename = %s", (filename,))
        mysql_deleted = cursor.rowcount
        cnx.commit()

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
        filename=filename
    )
    msg = f"Suppression en base : MySQL={mysql_deleted}, MongoDB={mongo_deleted}"
    return GPXDeleteResponse(success=True, message=msg, deleted_file=filename)