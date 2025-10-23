import sys
from pathlib import Path

def add_etl_paths(root=None):
    """
    Ajoute les dossiers ETL au sys.path pour permettre les imports locaux.
    root : Path vers la racine du projet. Si None, déduit automatiquement.
    """
    if root is None:
        root = Path(__file__).resolve().parents[2]
    sys.path.append(str(root / "etl/extract"))
    sys.path.append(str(root / "etl/load"))
    sys.path.append(str(root / "etl/transformation"))
