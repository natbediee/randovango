
import os
from pathlib import Path
from utils.logger_util import LoggerUtil

from etl.transform.transform_gpx import transform_gpx
from utils.db_utils import gpx_already_in_mysql

logger = LoggerUtil.get_logger("extract_gpx")

def extract_all_gpx_files() -> list:
    """
    Recherche tous les fichiers GPX dans le dossier défini par DATA,
    lit leur contenu, effectue la transformation, et retourne une liste de tuples (data, gpx_path, fname).
    """
    gpx_dir = Path("/usr/src/data")
    gpx_files = [f for f in os.listdir(gpx_dir) if f.endswith('.gpx')]
    if not gpx_files:
        logger.error(f"[ETL] Aucun fichier GPX trouvé dans {gpx_dir}")
        return []
    results = []
    for fname in gpx_files:
        gpx_path = os.path.join(gpx_dir, fname)
        # Vérification présence en base MySQL
        if gpx_already_in_mysql(fname):
            logger.info(f"[ETL] GPX déjà présent en base MySQL, suppression du fichier: {fname}")
            try:
                os.remove(gpx_path)
                logger.info(f"[ETL] Fichier supprimé : {gpx_path}")
            except Exception as e:
                logger.warning(f"[ETL] Erreur lors de la suppression du fichier {gpx_path} : {e}")
            continue
        logger.info(f"[ETL] Début du pipeline. Fichier GPX détecté: {fname}")
        with open(gpx_path, 'r') as gpx_file:
            gpx_content = gpx_file.read()
        data = transform_gpx(gpx_content, fname)
        if not data:
            logger.info(f"[ETL] Erreur lors de la transformation GPX pour {fname}. Fichier ignoré.")
            continue
        results.append((data, gpx_path, fname))
    return results
