"""
Restauration d'une sauvegarde des bases de Randovango (issue #205).

Deux usages :
- ouvrir une archive : elle est déchiffrée et ses fichiers posés dans un dossier, d'où on les
  recharge dans les bases (commandes dans docs/exploitation.md) :
      python3 scripts/restore.py ARCHIVE --dossier DOSSIER
- faire une restauration d'essai : l'archive est rechargée dans des conteneurs MySQL et Mongo
  jetables (sans port ouvert, effacés à la fin), puis le nombre de lignes de chaque table est
  comparé à celui relevé au moment de la sauvegarde (comptes.json). Les bases de travail ne
  sont pas touchées :
      python3 scripts/restore.py ARCHIVE --essai

Sur un autre ordinateur, sans le trousseau, --demander fait taper le mot de passe
sans l'afficher.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

import backup

# Conteneurs jetables de la restauration d'essai : mêmes versions que docker-compose.yml.
TRIAL_MYSQL = "randovango_essai_mysql"
TRIAL_MONGO = "randovango_essai_mongo"
TRIAL_DATABASE = "essai"
TRIAL_MYSQL_CONNECT = f"mysql -u root -h 127.0.0.1 {TRIAL_DATABASE}"
TRIAL_MONGO_CONNECT = f"mongosh {backup.MONGO_DATABASE}"


# --- Ouvrir une archive ------------------------------------------------------------------------

def is_safe_member(name: str) -> bool:
    """Vrai si un fichier de l'archive reste dans le dossier d'arrivée (ni chemin absolu, ni « .. »)."""
    path = Path(name)
    return not path.is_absolute() and ".." not in path.parts


def extract_archive(archive_path: Path, target: Path) -> None:
    """Pose les fichiers d'une archive .tar.gz dans target, en refusant les chemins qui en sortent."""
    with tarfile.open(archive_path, "r:gz") as archive:
        unsafe = [name for name in archive.getnames() if not is_safe_member(name)]
        if unsafe:
            sys.exit(f"Archive refusée, chemins dangereux : {unsafe}")
        archive.extractall(target)


def open_archive(encrypted: Path, target: Path, password: str) -> None:
    """Déchiffre l'archive puis l'ouvre dans target ; l'archive déchiffrée n'est pas gardée."""
    target.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="randovango-restauration-") as temporary:
        clear = Path(temporary) / "archive.tar.gz"
        try:
            backup.decrypt_file(encrypted, clear, password)
        except subprocess.CalledProcessError:
            sys.exit("Déchiffrement impossible : mot de passe faux ou archive abîmée.")
        extract_archive(clear, target)


# --- Comparer les comptes ----------------------------------------------------------------------

def compare_counts(expected: dict[str, int], actual: dict[str, int]) -> list[str]:
    """Liste les tables dont le nombre de lignes restaurées diffère de celui de la sauvegarde."""
    differences = []
    for table in sorted(set(expected) | set(actual)):
        before, after = expected.get(table), actual.get(table)
        if before != after:
            differences.append(f"{table} : {before} à la sauvegarde, {after} restaurées")
    return differences


# --- Restauration d'essai ----------------------------------------------------------------------

def start_trial_containers() -> None:
    """Démarre les conteneurs jetables : sans port publié, sans mot de passe, effacés à l'arrêt."""
    subprocess.run(["docker", "run", "-d", "--rm", "--name", TRIAL_MYSQL,
                    "-e", "MYSQL_ALLOW_EMPTY_PASSWORD=yes", "-e", f"MYSQL_DATABASE={TRIAL_DATABASE}",
                    "mysql:9.7"], check=True, capture_output=True)
    subprocess.run(["docker", "run", "-d", "--rm", "--name", TRIAL_MONGO, "mongo:7.0"],
                   check=True, capture_output=True)


def stop_trial_containers() -> None:
    """Arrête les conteneurs jetables ; --rm les efface avec leurs données."""
    subprocess.run(["docker", "stop", TRIAL_MYSQL, TRIAL_MONGO], capture_output=True)


def wait_until_ready(container: str, command: str, seconds: int = 120) -> None:
    """Attend qu'une base jetable réponde à command, au plus seconds secondes."""
    for _ in range(seconds):
        result = subprocess.run(["docker", "exec", container, "sh", "-c", command],
                                capture_output=True)
        if result.returncode == 0:
            return
        time.sleep(1)
    sys.exit(f"La base jetable {container} ne répond pas.")


def load_into_trial_containers(folder: Path) -> None:
    """Recharge les dumps de folder dans les conteneurs jetables."""
    # Piège : au premier démarrage, l'image MySQL lance un serveur provisoire, sans réseau,
    # le temps de créer la base. On attend donc une réponse par le réseau (-h 127.0.0.1) :
    # seul le vrai serveur la donne.
    wait_until_ready(TRIAL_MYSQL, f"{TRIAL_MYSQL_CONNECT} -e 'SELECT 1'")
    wait_until_ready(TRIAL_MONGO, "mongosh --quiet --eval 'db.adminCommand(\"ping\").ok'")
    with open(folder / "mysql.sql", "rb") as dump:
        subprocess.run(["docker", "exec", "-i", TRIAL_MYSQL, "sh", "-c", TRIAL_MYSQL_CONNECT],
                       stdin=dump, check=True)
    with open(folder / "mongo.archive.gz", "rb") as dump:
        subprocess.run(["docker", "exec", "-i", TRIAL_MONGO,
                        "mongorestore", "--quiet", "--archive", "--gzip"], stdin=dump, check=True)


def trial_counts(folder: Path) -> dict:
    """Compte les lignes restaurées : MySQL et Mongo jetables, et la base des comptes posée."""
    return {
        "mysql": backup.count_mysql_rows(TRIAL_MYSQL, TRIAL_MYSQL_CONNECT),
        "mongo": backup.count_mongo_documents(TRIAL_MONGO, TRIAL_MONGO_CONNECT),
        "sqlite": backup.count_sqlite_rows(folder / "rando_users.sqlite"),
    }


def report_trial(expected: dict, actual: dict) -> bool:
    """Affiche le résultat de l'essai base par base ; vrai si tout correspond."""
    all_equal = True
    for base in ("mysql", "mongo", "sqlite"):
        differences = compare_counts(expected[base], actual[base])
        total = sum(actual[base].values())
        if differences:
            all_equal = False
            print(f"{base} : DIFFÉRENCES")
            for line in differences:
                print(f"  {line}")
        else:
            # Mongo range ses documents dans des « collections », les deux autres bases dans des tables.
            unit = "collections" if base == "mongo" else "tables"
            print(f"{base} : {len(actual[base])} {unit}, {total} lignes, identiques à la sauvegarde")
    return all_equal


def trial_restore(encrypted: Path, password: str) -> bool:
    """Restauration d'essai complète, dans des conteneurs jetables ; vrai si elle est fidèle."""
    with tempfile.TemporaryDirectory(prefix="randovango-essai-") as temporary:
        folder = Path(temporary)
        open_archive(encrypted, folder, password)
        expected = json.loads((folder / "comptes.json").read_text())
        print(f"Archive du {expected['date']} ouverte. Démarrage des bases jetables…")
        start_trial_containers()
        try:
            load_into_trial_containers(folder)
            return report_trial(expected, trial_counts(folder))
        finally:
            stop_trial_containers()


def parse_arguments() -> argparse.Namespace:
    """Lit les options de la ligne de commande."""
    parser = argparse.ArgumentParser(description="Ouvre ou essaie une sauvegarde chiffrée.")
    parser.add_argument("archive", type=Path, help="le fichier randovango_….tar.gz.enc")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--dossier", type=Path, help="dossier où poser les fichiers de l'archive")
    action.add_argument("--essai", action="store_true",
                        help="restauration d'essai dans des bases jetables, puis comparaison")
    parser.add_argument("--demander", action="store_true",
                        help="demander le mot de passe au clavier au lieu du trousseau")
    return parser.parse_args()


if __name__ == "__main__":
    options = parse_arguments()
    secret = backup.get_password(options.demander)
    if options.essai:
        sys.exit(0 if trial_restore(options.archive, secret) else 1)
    open_archive(options.archive, options.dossier, secret)
    print(f"Archive ouverte dans {options.dossier} ; suite dans docs/exploitation.md.")
