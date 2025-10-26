import os
from backend.utils.logger_util import LoggerUtil
from backend.utils.service_utils import ServiceUtil
from backend.etl.transform.transform_gpx import transform_gpx

logger = LoggerUtil.get_logger("extract_gpx")

def extract_gpx_file() -> tuple[dict | None, str | None, str | None]:
    """
    Recherche le premier fichier GPX dans le dossier défini par DATA_GPX,
    lit son contenu, effectue la transformation, et retourne le résultat.
    Retourne (data, gpx_path, fname) ou (None, None, None) si erreur.
    """
    gpx_dir = ServiceUtil.get_env('DATA_GPX', 'data/in/gpx')
    gpx_files = [f for f in os.listdir(gpx_dir) if f.endswith('.gpx')]
    if not gpx_files:
        logger.error(f"[ETL] Aucun fichier GPX trouvé dans {gpx_dir}")
        return None, None, None
    logger.info(f"[ETL] Début du pipeline. Fichier GPX détecté: {gpx_files[0]}")
    fname = gpx_files[0]
    gpx_path = os.path.join(gpx_dir, fname)
    with open(gpx_path, 'r') as gpx_file:
        gpx_content = gpx_file.read()
    # --- Transformation explicite ---
    data = transform_gpx(gpx_content, fname)
    if not data:
        logger.info("[ETL] Erreur lors de la transformation GPX. Arrêt du pipeline.")
        return None, None, None
    return data, gpx_path, fname
