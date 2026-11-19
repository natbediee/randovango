"""
Les scripts de sauvegarde (scripts/backup.py, scripts/restore.py) tournent sur le Mac, hors du
backend : ce fichier rend leur dossier importable par les tests de ce dossier.
"""
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
