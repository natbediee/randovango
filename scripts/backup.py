"""
Sauvegarde des bases de Randovango hors de la machine (issue #205).

Pourquoi : les données ont coûté des centaines de dollars d'agents et des heures de supervision.
Une copie rangée sur le même disque que les bases ne protège pas d'une panne de la machine ; ce script
en fait une copie chiffrée sur iCloud Drive, à lancer avant chaque gros passage.

Ce que contient l'archive :
- mysql.sql            : le dump de la base MySQL (conteneur db_randovango) ;
- mongo.archive.gz     : le dump de la base Mongo (conteneur mongo_randovango) ;
- rando_users.sqlite   : la base des comptes (storage/rando_users.sqlite) ;
- logs/                : les fichiers de trace des passages (journaux, résultats des agents) ;
- comptes.json         : le nombre de lignes de chaque table, pour vérifier une restauration.
Le .env n'y est jamais : il est gardé à part, hors de la machine.

Le mot de passe de l'archive est lu dans le trousseau du système : il n'est écrit ni dans le code,
ni dans l'historique du terminal. Il doit aussi être gardé hors de la machine, sinon
l'archive ne pourrait plus être ouverte si la machine (et donc son trousseau) disparaissait.

Lancement (depuis le dossier du projet, conteneurs démarrés) :
    python3 scripts/backup.py
La procédure complète est dans docs/exploitation.md.

Le script tourne sur la machine, pas dans un conteneur : il n'utilise que la bibliothèque standard
de Python (3.9 suffit), plus docker, openssl et la commande security (le trousseau du système).
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path

# Le dossier du projet : celui qui contient scripts/, storage/ et logs/.
PROJECT_DIR = Path(__file__).resolve().parents[1]

# Le dossier d'iCloud Drive ; le système envoie tout seul sur iCloud ce qu'on y dépose.
DRIVE_DIR = Path.home() / "Library/Mobile Documents/com~apple~CloudDocs/Randovango-sauvegardes"

# Nombre de versions datées gardées sur le drive : au-delà, les plus anciennes sont effacées.
KEEP = 10

MYSQL_CONTAINER = "db_randovango"
MONGO_CONTAINER = "mongo_randovango"
MONGO_DATABASE = "randovango"

# Nom de l'entrée du trousseau qui garde le mot de passe des archives.
KEYCHAIN_SERVICE = "randovango-sauvegarde"

# Nom de la variable qui passe le mot de passe à openssl : elle n'existe que dans le
# processus openssl, le temps du chiffrement, et n'est jamais affichée ni enregistrée.
PASSWORD_VARIABLE = "RANDOVANGO_BACKUP_PASSWORD"

# Chiffrement : AES-256, clé tirée du mot de passe par PBKDF2 (200 000 tours, pour ralentir
# qui essaierait de deviner le mot de passe). Les mêmes options servent à déchiffrer.
OPENSSL_OPTIONS = ["-aes-256-cbc", "-pbkdf2", "-iter", "200000", "-md", "sha256"]

# Nom d'une archive : randovango_AAAAMMJJ_HHMMSS.tar.gz.enc. La date dans le nom permet de
# trier les versions sans lire les fichiers.
ARCHIVE_PATTERN = re.compile(r"^randovango_\d{8}_\d{6}\.tar\.gz\.enc$")


# --- Mot de passe ------------------------------------------------------------------------------

def read_password_from_keychain() -> str:
    """Lit le mot de passe des archives dans le trousseau du système, sans jamais l'afficher."""
    result = subprocess.run(
        ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", getpass.getuser(), "-w"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        sys.exit(
            "Mot de passe introuvable dans le trousseau. Range-le une fois avec :\n"
            f'  security add-generic-password -s {KEYCHAIN_SERVICE} -a "$USER" -w\n'
            "(la commande le demande sans l'afficher), et garde-le aussi hors de la machine."
        )
    return result.stdout.rstrip("\n")


def ask_password() -> str:
    """Demande le mot de passe au clavier sans l'afficher (sur un ordinateur sans le trousseau)."""
    return getpass.getpass("Mot de passe de l'archive : ")


def get_password(ask: bool) -> str:
    """Donne le mot de passe : demandé au clavier si ask est vrai, sinon lu dans le trousseau."""
    password = ask_password() if ask else read_password_from_keychain()
    if not password:
        sys.exit("Mot de passe vide : rien n'est chiffré ni déchiffré.")
    return password


# --- Chiffrement -------------------------------------------------------------------------------

def run_openssl(arguments: list[str], password: str) -> None:
    """Lance openssl en lui passant le mot de passe par une variable propre à ce seul processus."""
    environment = dict(os.environ)
    environment[PASSWORD_VARIABLE] = password
    subprocess.run(
        ["openssl", "enc", *arguments, *OPENSSL_OPTIONS, "-pass", f"env:{PASSWORD_VARIABLE}"],
        env=environment,
        check=True,
    )


def encrypt_file(source: Path, target: Path, password: str) -> None:
    """Chiffre source dans target (AES-256) ; seul le mot de passe permet de le relire."""
    run_openssl(["-e", "-salt", "-in", str(source), "-out", str(target)], password)


def decrypt_file(source: Path, target: Path, password: str) -> None:
    """Déchiffre source dans target ; openssl échoue si le mot de passe est faux."""
    run_openssl(["-d", "-in", str(source), "-out", str(target)], password)


# --- Dumps des trois bases ---------------------------------------------------------------------

def run_in_container(container: str, command: str, output: Path | None = None,
                     input_text: str | None = None) -> str:
    """
    Lance une commande shell dans un conteneur. Les mots de passe des bases ne passent pas par
    ce script : la commande lit ceux du conteneur ($MYSQL_ROOT_PASSWORD…), qui les a reçus du .env.
    Si output est donné, la sortie est écrite dans ce fichier (un dump peut être gros).
    Si input_text est donné, il est envoyé à la commande sur son entrée (une requête SQL, par exemple).
    """
    arguments = ["docker", "exec", "-i", container, "sh", "-c", command]
    if output is None:
        return subprocess.run(arguments, input=input_text, capture_output=True, text=True,
                              check=True).stdout
    with open(output, "wb") as file:
        subprocess.run(arguments, stdout=file, check=True)
    return ""


def dump_mysql(target: Path) -> None:
    """Fait le dump de la base MySQL, et vérifie qu'il est allé jusqu'au bout."""
    # --single-transaction : une photo cohérente de la base, même si un script y écrit pendant le dump.
    # Les autres options sont expliquées dans docs/exploitation.md (restauration sur un autre serveur).
    run_in_container(
        MYSQL_CONTAINER,
        'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysqldump -u root --single-transaction --no-tablespaces '
        '--set-gtid-purged=OFF --skip-masking-policies --routines --triggers "$MYSQL_DATABASE"',
        output=target,
    )
    if not is_complete_mysql_dump(target):
        sys.exit(f"Dump MySQL incomplet ({target}) : la sauvegarde est arrêtée.")


def is_complete_mysql_dump(path: Path) -> bool:
    """Un dump MySQL complet finit par la ligne « -- Dump completed on … »."""
    with open(path, "rb") as file:
        file.seek(0, os.SEEK_END)
        file.seek(max(0, file.tell() - 200))
        return b"-- Dump completed" in file.read()


def dump_mongo(target: Path) -> None:
    """Fait le dump de la base Mongo en un seul fichier compressé (format archive de mongodump)."""
    run_in_container(
        MONGO_CONTAINER,
        'mongodump --quiet --archive --gzip -u "$MONGO_INITDB_ROOT_USERNAME" '
        f'-p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin --db {MONGO_DATABASE}',
        output=target,
    )


def copy_sqlite(source: Path, target: Path) -> None:
    """
    Copie la base des comptes avec la sauvegarde intégrée de SQLite : contrairement à une simple
    copie de fichier, elle reste juste même si l'API écrit dans la base au même moment.
    """
    if not source.exists():
        sys.exit(f"Base des comptes introuvable : {source}")
    with sqlite3.connect(source) as origin, sqlite3.connect(target) as copy:
        origin.backup(copy)
    # Sous Python 3.9, « with » valide mais ne ferme pas la connexion : on la ferme nous-mêmes.
    origin.close()
    copy.close()


# --- Comptes de lignes, pour vérifier une restauration -----------------------------------------

def parse_tab_counts(text: str) -> dict[str, int]:
    """Lit des lignes « nom<tab>nombre » (sortie de mysql -N) en un dictionnaire."""
    counts = {}
    for line in text.splitlines():
        if line.strip():
            name, number = line.split("\t")
            counts[name] = int(number)
    return counts


def mysql_counts_query(tables: list[str]) -> str:
    """Construit une requête qui compte les lignes de chaque table, en un seul aller-retour."""
    parts = [f"SELECT '{table}', COUNT(*) FROM `{table}`" for table in tables]
    return " UNION ALL ".join(parts)


def count_mysql_rows(container: str, connect: str) -> dict[str, int]:
    """Compte les lignes de chaque table MySQL ; connect est la commande mysql qui se connecte."""
    # Les requêtes passent par l'entrée de mysql, pas par -e "…" : le shell du conteneur
    # prendrait sinon les accents graves des noms de tables pour une commande à lancer.
    tables_text = run_in_container(
        container, f"{connect} -N", input_text="SHOW FULL TABLES WHERE Table_type = 'BASE TABLE';"
    )
    tables = [line.split("\t")[0] for line in tables_text.splitlines() if line.strip()]
    if not tables:
        return {}
    return parse_tab_counts(run_in_container(container, f"{connect} -N",
                                             input_text=mysql_counts_query(tables) + ";"))


def count_mongo_documents(container: str, connect: str) -> dict[str, int]:
    """Compte les documents de chaque collection Mongo ; connect est la commande mongosh."""
    script = (
        "const r = {}; db.getCollectionNames().forEach(c => r[c] = db.getCollection(c)"
        ".countDocuments()); print(JSON.stringify(r))"
    )
    return json.loads(run_in_container(container, f"{connect} --quiet --eval '{script}'"))


def count_sqlite_rows(path: Path) -> dict[str, int]:
    """Compte les lignes de chaque table d'une base SQLite."""
    connection = sqlite3.connect(path)
    try:
        tables = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )]
        return {t: connection.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}
    finally:
        connection.close()


# Commandes de connexion aux bases de travail ; les mots de passe sont lus dans le conteneur.
WORK_MYSQL_CONNECT = 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -u root "$MYSQL_DATABASE"'
WORK_MONGO_CONNECT = (
    'mongosh -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" '
    f"--authenticationDatabase admin {MONGO_DATABASE}"
)


# --- Archive -----------------------------------------------------------------------------------

def is_secret_file(name: str) -> bool:
    """Vrai pour un .env (ou .env.quelquechose) : ces fichiers ne vont jamais dans l'archive."""
    base = Path(name).name
    return base == ".env" or base.startswith(".env.")


def skip_secrets(member: tarfile.TarInfo) -> tarfile.TarInfo | None:
    """Filtre de tarfile : écarte tout .env qui traînerait dans un dossier ajouté à l'archive."""
    return None if is_secret_file(member.name) else member


def build_archive(work_dir: Path, logs_dir: Path, target: Path) -> None:
    """Rassemble les dumps du dossier de travail et le dossier des traces dans un .tar.gz."""
    with tarfile.open(target, "w:gz") as archive:
        for item in sorted(work_dir.iterdir()):
            archive.add(item, arcname=item.name, filter=skip_secrets)
        if logs_dir.is_dir():
            archive.add(logs_dir, arcname="logs", filter=skip_secrets)


def check_no_secret(archive_path: Path) -> None:
    """Relit la liste des fichiers de l'archive et s'arrête si un .env s'y trouve."""
    with tarfile.open(archive_path, "r:gz") as archive:
        secrets = [name for name in archive.getnames() if is_secret_file(name)]
    if secrets:
        sys.exit(f"Un .env s'est glissé dans l'archive ({secrets}) : la sauvegarde est arrêtée.")


# --- Versions datées sur le drive --------------------------------------------------------------

def archive_name(moment: datetime) -> str:
    """Le nom daté d'une archive, par exemple randovango_20261119_143005.tar.gz.enc."""
    return moment.strftime("randovango_%Y%m%d_%H%M%S.tar.gz.enc")


def visible_name(file_name: str) -> str:
    """
    Le vrai nom d'une archive dans le dossier iCloud. Piège : quand iCloud libère de la place,
    il remplace le fichier par un repère « .nom.icloud » ; c'est toujours la même archive.
    """
    if file_name.startswith(".") and file_name.endswith(".icloud"):
        return file_name[1:-len(".icloud")]
    return file_name


def archives_to_delete(file_names: list[str], keep: int) -> list[str]:
    """Les fichiers d'archives à effacer pour n'en garder que les keep plus récentes."""
    archives = [name for name in file_names if ARCHIVE_PATTERN.match(visible_name(name))]
    # La date est dans le nom : l'ordre alphabétique est aussi l'ordre chronologique.
    archives.sort(key=visible_name)
    return archives[:-keep] if len(archives) > keep else []


def remove_old_archives(destination: Path, keep: int) -> list[str]:
    """Efface les archives les plus anciennes du drive ; les autres fichiers ne sont pas touchés."""
    names = archives_to_delete([path.name for path in destination.iterdir()], keep)
    for name in names:
        (destination / name).unlink()
    return names


def copy_to_destination(encrypted: Path, destination: Path, name: str) -> Path:
    """
    Copie l'archive chiffrée sur le drive. Elle est écrite sous un nom provisoire puis renommée :
    iCloud n'envoie ainsi jamais une archive à moitié copiée.
    """
    destination.mkdir(parents=True, exist_ok=True)
    temporary = destination / f"{name}.part"
    shutil.copyfile(encrypted, temporary)
    final = destination / name
    temporary.rename(final)
    return final


# --- Sauvegarde complète -----------------------------------------------------------------------

def dump_everything(project_dir: Path, work_dir: Path) -> dict:
    """Fait les trois dumps dans work_dir et y écrit comptes.json ; renvoie ces comptes."""
    print("Dump de MySQL…")
    dump_mysql(work_dir / "mysql.sql")
    print("Dump de Mongo…")
    dump_mongo(work_dir / "mongo.archive.gz")
    print("Copie de la base des comptes…")
    copy_sqlite(project_dir / "storage" / "rando_users.sqlite", work_dir / "rando_users.sqlite")
    counts = {
        "date": datetime.now().isoformat(timespec="seconds"),
        "mysql": count_mysql_rows(MYSQL_CONTAINER, WORK_MYSQL_CONNECT),
        "mongo": count_mongo_documents(MONGO_CONTAINER, WORK_MONGO_CONNECT),
        "sqlite": count_sqlite_rows(work_dir / "rando_users.sqlite"),
    }
    (work_dir / "comptes.json").write_text(json.dumps(counts, indent=2, ensure_ascii=False))
    return counts


def backup(project_dir: Path, destination: Path, keep: int, ask: bool) -> Path:
    """Fait la sauvegarde complète : dumps, archive, chiffrement, copie sur le drive, ménage."""
    password = get_password(ask)
    # Le dossier temporaire est effacé à la fin, avec les dumps en clair qu'il contient.
    with tempfile.TemporaryDirectory(prefix="randovango-sauvegarde-") as temporary:
        work_dir = Path(temporary) / "contenu"
        work_dir.mkdir()
        counts = dump_everything(project_dir, work_dir)
        archive = Path(temporary) / "archive.tar.gz"
        print("Archive des dumps et de logs/…")
        build_archive(work_dir, project_dir / "logs", archive)
        check_no_secret(archive)
        print("Chiffrement…")
        encrypted = Path(temporary) / "archive.tar.gz.enc"
        encrypt_file(archive, encrypted, password)
        final = copy_to_destination(encrypted, destination, archive_name(datetime.now()))
    removed = remove_old_archives(destination, keep)
    print_summary(final, counts, removed)
    return final


def print_summary(final: Path, counts: dict, removed: list[str]) -> None:
    """Affiche ce qui a été sauvegardé, pour le garder dans le journal du passage."""
    size = final.stat().st_size / (1024 * 1024)
    print(f"\nSauvegarde écrite : {final} ({size:.1f} Mo)")
    print(f"MySQL : {len(counts['mysql'])} tables, {sum(counts['mysql'].values())} lignes")
    print(f"Mongo : {counts['mongo']}")
    print(f"Comptes : {counts['sqlite']}")
    for name in removed:
        print(f"Ancienne version effacée : {name}")


def parse_arguments() -> argparse.Namespace:
    """Lit les options de la ligne de commande."""
    parser = argparse.ArgumentParser(description="Sauvegarde chiffrée des bases sur le drive.")
    parser.add_argument("--projet", type=Path, default=PROJECT_DIR,
                        help="dossier du projet qui contient storage/ et logs/")
    parser.add_argument("--destination", type=Path, default=DRIVE_DIR,
                        help="dossier du drive où déposer l'archive")
    parser.add_argument("--garder", type=int, default=KEEP, help="nombre de versions gardées")
    parser.add_argument("--demander", action="store_true",
                        help="demander le mot de passe au clavier au lieu du trousseau")
    return parser.parse_args()


if __name__ == "__main__":
    options = parse_arguments()
    backup(options.projet, options.destination, options.garder, options.demander)
