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

from etl.extract.same_path import find_same_path_hike, same_path_reason
from etl.transform.transform_gpx import transform_gpx
from utils.db_utils import gpx_already_in_mysql

logger = LoggerUtil.get_logger("etl_gpx")

# Le dossier d'attente : on y dépose les fichiers d'un envoi en masse, que le pipeline vide un à un, en fond.
GPX_DIR = Path("/usr/src/data")
# Le fichier envoyé par la page d'ajout (route upload_gpx) attend à part, dans un sous-dossier (issue #328) : il est
# traité tout de suite, avant ceux du dossier d'attente, et le fil qui vide le dossier ne le voit jamais.
UPLOAD_DIR = GPX_DIR / "envoi"

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


def read_gpx_file(gpx_path, fname, allow_same_path=False) -> dict:
    """
    Lit un fichier du dossier d'attente et rend son résultat : les données prêtes à charger, ou le motif du refus.
    Un fichier refusé est retiré du dossier tout de suite.
    Un tracé qui suit le même chemin qu'une rando déjà en base est refusé aussi, même sous un autre nom de fichier
    (issue #271) : « same_path » donne alors cette rando, pour que la page d'ajout puisse la nommer.
    allow_same_path : l'admin a vu ce refus et confirme le chargement (un autre départ peut avoir son intérêt pour
    le voyageur). Un tracé identique à une rando en base reste refusé, même avec cette confirmation.
    """
    result = {"filename": fname, "gpx_path": gpx_path, "data": None, "reason": None, "same_path": None}
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
            else:
                refuse_same_path(result, allow_same_path)
    if result["reason"]:
        logger.info(f"[Extract] : Fichier {fname} refusé : {result['reason']}")
        remove_file(gpx_path)
    return result


def refuse_same_path(result, allow_same_path) -> None:
    """
    Refuse le tracé lu s'il suit le même chemin qu'une rando déjà en base (recouvert à 85 % ou plus, dans les deux
    sens) : le motif nomme cette rando, et ses données ne sont pas chargées. Si l'admin a confirmé (allow_same_path),
    le tracé passe, sauf s'il est identique à cette rando : c'est alors la même, et le refus reste.
    """
    same_path = find_same_path_hike(result["data"]["points"])
    if not same_path:
        return
    if allow_same_path and not same_path["identical"]:
        logger.info(f"[Extract] : {result['filename']} chargé à la demande de l'admin, bien qu'il suive le chemin de "
                    f"la rando {same_path['id']} ({same_path['name']})")
        return
    result["same_path"] = same_path
    result["reason"] = same_path_reason(same_path)
    result["data"] = None


def waiting_files() -> list:
    """
    Les noms des fichiers GPX du dossier d'attente, par ordre alphabétique. Le sous-dossier « envoi » n'en fait pas
    partie. L'extension est comparée en minuscules : la route accepte « RANDO.GPX », qui ne doit pas rester oublié ici.
    """
    if not os.path.isdir(GPX_DIR):
        return []
    return sorted(f for f in os.listdir(GPX_DIR) if f.lower().endswith('.gpx') and os.path.isfile(os.path.join(GPX_DIR, f)))
