from utils.db_utils import MySQLUtils
from utils.mongo_utils import MongoUtils
from fastapi import APIRouter, UploadFile, File, Depends
from api.dependencies import get_current_user, require_admin
from api.models.etl import GPXUploadResponse, GPXDeleteResponse
from etl.etl_pipeline import process_upload
from etl.extract.gpx import UPLOAD_DIR
from services.authentification import get_roles_for_user, insert_auth_log

router = APIRouter()

ALLOWED_EXT = {"gpx"}


@router.post("/upload_gpx", summary="Upload a GPX file and launch the ETL pipeline (Admin and Contributor only)", response_model=GPXUploadResponse)
def upload_gpx(
    file: UploadFile = File(..., description="Fichier GPX"),
    user=Depends(get_current_user)
):
    """
    Reçoit le GPX d'une rando depuis la page d'ajout, le charge en base et dit ce qui s'est vraiment passé :
    la ville du tracé chargé, ou le motif du refus (issue #266).
    Seul ce fichier est attendu : ceux d'un envoi en masse, déposés dans le dossier d'attente, passent ensuite, en fond.
    Une route « def », et non « async def » (issue #328) : le pipeline attend la base et des API sans rendre la main.
    Dans une route « async def », il bloquait tout le serveur : le 25 novembre 2026, pendant les 5 minutes d'un envoi
    de 240 randos, ni l'application ni la supervision ne répondaient. Une route « def », FastAPI la fait tourner à
    part (dans un fil de son groupe de fils) : les autres requêtes continuent d'être servies pendant l'envoi.
    """
    # Récupérer le rôle de l'utilisateur
    user_id = user["user_id"]
    roles = get_roles_for_user(user_id)
    user_role = "admin" if "admin" in roles else "user"
    # Vérification extension
    ext = file.filename.split(".")[-1].lower()
    if ext not in ALLOWED_EXT:
        return GPXUploadResponse(success=False, message=f"Extension non autorisée: {ext}")
    # Le fichier envoyé attend à part, dans le sous-dossier « envoi » du dossier d'attente (volume Docker) : il est
    # traité tout de suite, avant les fichiers d'un envoi en masse déposés dans le dossier (issue #328).
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    dest_path = UPLOAD_DIR / file.filename
    with open(dest_path, "wb") as f:
        # file.file : le fichier reçu, lu directement, puisqu'une route « def » ne peut pas attendre file.read().
        f.write(file.file.read())
    # Le pipeline traite ce seul fichier et rend son résultat ; les fichiers du dossier d'attente passent après, en fond.
    try:
        outcome = process_upload(dest_path, user_role=user_role)
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