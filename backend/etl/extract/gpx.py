import os
from utils.logger_util import LoggerUtil
from utils.service_utils import ServiceUtil
from etl.transform.transform_gpx import transform_gpx

logger = LoggerUtil.get_logger("extract_gpx")

def extract_all_gpx_files() -> list:
    """
    Recherche tous les fichiers GPX dans le dossier défini par DATA_IN,
    lit leur contenu, effectue la transformation, et retourne une liste de tuples (data, gpx_path, fname).
    """
    gpx_dir = ServiceUtil.get_env('DATA_IN', 'data/in')
    gpx_files = [f for f in os.listdir(gpx_dir) if f.endswith('.gpx')]
    if not gpx_files:
        logger.error(f"[ETL] Aucun fichier GPX trouvé dans {gpx_dir}")
        return []
    results = []
    for fname in gpx_files:
        gpx_path = os.path.join(gpx_dir, fname)
        logger.info(f"[ETL] Début du pipeline. Fichier GPX détecté: {fname}")
        with open(gpx_path, 'r') as gpx_file:
            gpx_content = gpx_file.read()
        data = transform_gpx(gpx_content, fname)
        if not data:
            logger.info(f"[ETL] Erreur lors de la transformation GPX pour {fname}. Fichier ignoré.")
            continue
        results.append((data, gpx_path, fname))
    return results
