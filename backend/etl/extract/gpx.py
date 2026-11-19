"""
Lecture des fichiers GPX déposés dans le dossier d'attente (/usr/src/data) par la page d'ajout d'une rando.

Chaque fichier est lu, contrôlé puis transformé. Un fichier qui ne peut pas être chargé est refusé avec un motif
que la page d'ajout affiche à l'admin ou au contributeur, et il est retiré du dossier : sans cela, il repasserait
à chaque envoi suivant (issue #266).
"""
import os
from pathlib import Path

import gpxpy
from utils.logger_util import LoggerUtil

from etl.transform.transform_gpx import transform_gpx
from utils.db_utils import gpx_already_in_mysql

logger = LoggerUtil.get_logger("etl_gpx")

# Le dossier d'attente : la route upload_gpx y écrit le fichier envoyé, le pipeline le vide.
GPX_DIR = Path("/usr/src/data")

# Les motifs de refus, écrits pour la personne qui envoie le fichier (issue #266).
ALREADY_LOADED = "cette rando est déjà en base (un fichier du même nom a déjà été chargé)"
UNREADABLE = "le fichier n'est pas un GPX lisible"
ROUTE_ONLY = "il ne contient pas une trace complète"
NO_TRACK = "le fichier ne contient aucune trace"
START_NOT_FOUND = "le lieu de départ est introuvable : aucune commune trouvée au premier point de la trace"
LOAD_FAILED = "une erreur est survenue pendant l'enregistrement en base"


def remove_file(gpx_path) -> None:
    """Retire un fichier du dossier d'attente, une fois chargé ou refusé, pour qu'il ne repasse pas au prochain envoi."""
    try:
        os.remove(gpx_path)
        logger.info(f"[Extract] : Fichier supprimé : {gpx_path}")
    except OSError as e:
        logger.warning(f"[Extract] : Erreur lors de la suppression du fichier {gpx_path} : {e}")


def track_refusal(gpx_content) -> str | None:
    """
    Dit pourquoi le contenu ne peut pas devenir une rando, ou None s'il contient une trace.

    Seule une trace (<trk>) est chargée : c'est le chemin réellement parcouru. Une route (<rte>) n'est qu'un
    itinéraire prévu, souvent quelques points de virage sans altitude : la distance, le dénivelé et la durée
    calculés dessus seraient faux pour le voyageur. Choix de l'utilisatrice du 19 novembre 2026 : on la refuse,
    avec un message simple (« il ne contient pas une trace complète »).
    """
    try:
        gpx = gpxpy.parse(gpx_content)
    except Exception as e:  # gpxpy lève plusieurs sortes d'erreurs selon ce qui est cassé (XML, attributs...)
        logger.info(f"[Extract] : GPX illisible : {e}")
        return UNREADABLE
    has_track_points = any(segment.points for track in gpx.tracks for segment in track.segments)
    if has_track_points:
        return None
    if gpx.routes:
        return ROUTE_ONLY
    return NO_TRACK


def read_gpx_file(gpx_path, fname) -> dict:
    """
    Lit un fichier du dossier d'attente et rend son résultat : les données prêtes à charger, ou le motif du refus.
    Un fichier refusé est retiré du dossier tout de suite.
    """
    result = {"filename": fname, "gpx_path": gpx_path, "data": None, "reason": None}
    if gpx_already_in_mysql(fname):
        result["reason"] = ALREADY_LOADED
    else:
        with open(gpx_path, 'r', encoding='utf-8', errors='replace') as gpx_file:
            gpx_content = gpx_file.read()
        result["reason"] = track_refusal(gpx_content)
        if not result["reason"]:
            # transform_gpx ne rend rien quand aucune commune n'est trouvée au départ de la trace.
            result["data"] = transform_gpx(gpx_content, fname)
            if not result["data"]:
                result["reason"] = START_NOT_FOUND
    if result["reason"]:
        logger.info(f"[Extract] : Fichier {fname} refusé : {result['reason']}")
        remove_file(gpx_path)
    return result


def extract_all_gpx_files() -> list:
    """
    Lit tous les fichiers GPX du dossier d'attente et rend, pour chacun, le résultat de read_gpx_file.
    L'extension est comparée en minuscules : la route accepte « RANDO.GPX », qui ne doit pas rester oublié ici.
    """
    gpx_files = [f for f in os.listdir(GPX_DIR) if f.lower().endswith('.gpx')]
    if not gpx_files:
        logger.error(f"[Extract] : Aucun fichier GPX trouvé dans {GPX_DIR}")
        return []
    results = []
    for fname in gpx_files:
        logger.info(f"[Extract] : Début du pipeline. Fichier GPX détecté: {fname}")
        results.append(read_gpx_file(os.path.join(GPX_DIR, fname), fname))
    return results
