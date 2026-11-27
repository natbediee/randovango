"""
Sauvegarde des bases hors de la machine (scripts/backup.py et scripts/restore.py, issue #205).
Ni Docker ni trousseau : les dumps des conteneurs sont remplacés par de petits fichiers, et le
chiffrement utilise un mot de passe de test. openssl, lui, est le vrai.
"""
import json
import sqlite3
import tarfile
from datetime import datetime

import pytest

import backup
import restore

TEST_PASSWORD = "mot-de-passe-de-test"


def make_sqlite(path, users=3):
    """Crée une petite base des comptes, avec users comptes."""
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT)")
    connection.executemany("INSERT INTO users (email) VALUES (?)",
                           [(f"compte{i}@exemple.fr",) for i in range(users)])
    connection.commit()
    connection.close()


def make_work_dir(tmp_path):
    """Un dossier de travail comme celui des dumps, et un dossier logs/ avec un .env égaré."""
    work_dir = tmp_path / "contenu"
    work_dir.mkdir()
    (work_dir / "mysql.sql").write_text("CREATE TABLE spots (id INT);\n-- Dump completed on 2026\n")
    (work_dir / "comptes.json").write_text(json.dumps({"date": "2026-11-19T10:00:00",
                                                       "mysql": {"spots": 0}}))
    logs_dir = tmp_path / "logs"
    (logs_dir / "agent_restaurants").mkdir(parents=True)
    (logs_dir / "agent_restaurants" / "Brest_20261104.json").write_text("{}")
    (logs_dir / "etl_osm.log").write_text("passage OSM\n")
    (logs_dir / ".env").write_text("SECRET=1\n")
    (logs_dir / "agent_restaurants" / ".env.local").write_text("SECRET=2\n")
    return work_dir, logs_dir


# --- Le .env n'est jamais dans l'archive -------------------------------------------------------

def test_is_secret_file_recognises_env_files():
    """Un .env ou un .env.quelquechose est reconnu comme secret, pas un fichier qui en parle."""
    assert backup.is_secret_file(".env")
    assert backup.is_secret_file("logs/.env.local")
    assert not backup.is_secret_file("logs/env_check.log")
    assert not backup.is_secret_file("logs/mon.env.log")


def test_build_archive_leaves_env_files_out(tmp_path):
    """L'archive contient les dumps et les traces des passages, mais aucun .env égaré dans logs/."""
    work_dir, logs_dir = make_work_dir(tmp_path)
    archive_path = tmp_path / "archive.tar.gz"
    backup.build_archive(work_dir, logs_dir, archive_path)
    with tarfile.open(archive_path, "r:gz") as archive:
        names = archive.getnames()
    assert "mysql.sql" in names
    assert "comptes.json" in names
    assert "logs/agent_restaurants/Brest_20261104.json" in names
    assert "logs/etl_osm.log" in names
    assert not [name for name in names if ".env" in name]
    backup.check_no_secret(archive_path)


def test_check_no_secret_stops_when_env_is_inside(tmp_path):
    """Si un .env s'est glissé dans l'archive malgré tout, la sauvegarde s'arrête."""
    env_file = tmp_path / ".env"
    env_file.write_text("SECRET=1\n")
    archive_path = tmp_path / "archive.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        archive.add(env_file, arcname=".env")
    with pytest.raises(SystemExit):
        backup.check_no_secret(archive_path)


# --- Chiffrement par mot de passe --------------------------------------------------------------

def test_encrypted_archive_reopens_only_with_its_password(tmp_path):
    """L'archive chiffrée se rouvre avec son mot de passe, et pas avec un autre."""
    source = tmp_path / "clair.txt"
    source.write_text("données des spots")
    encrypted = tmp_path / "clair.txt.enc"
    backup.encrypt_file(source, encrypted, TEST_PASSWORD)
    assert b"spots" not in encrypted.read_bytes()

    reopened = tmp_path / "rouvert.txt"
    backup.decrypt_file(encrypted, reopened, TEST_PASSWORD)
    assert reopened.read_text() == "données des spots"

    with pytest.raises(Exception):
        backup.decrypt_file(encrypted, tmp_path / "faux.txt", "mauvais-mot-de-passe")


def test_get_password_refuses_an_empty_password(monkeypatch):
    """Un mot de passe vide arrête tout : jamais d'archive chiffrée avec un mot de passe vide."""
    monkeypatch.setattr(backup, "ask_password", lambda: "")
    with pytest.raises(SystemExit):
        backup.get_password(ask=True)


# --- Versions datées sur le drive --------------------------------------------------------------

def test_archive_name_carries_the_date():
    """Le nom d'une archive porte sa date et son heure, et suit le modèle des versions gardées."""
    name = backup.archive_name(datetime(2026, 11, 19, 14, 30, 5))
    assert name == "randovango_20261119_143005.tar.gz.enc"
    assert backup.ARCHIVE_PATTERN.match(name)


def test_archives_to_delete_keeps_the_most_recent():
    """Au-delà du nombre de versions gardées, ce sont les plus anciennes qui partent."""
    names = [f"randovango_202611{day:02d}_120000.tar.gz.enc" for day in range(1, 13)]
    to_delete = backup.archives_to_delete(list(reversed(names)), keep=10)
    assert to_delete == ["randovango_20261101_120000.tar.gz.enc",
                         "randovango_20261102_120000.tar.gz.enc"]


def test_archives_to_delete_ignores_other_files():
    """Les autres fichiers du dossier du drive (notes, archives en cours de copie) ne sont jamais effacés."""
    names = ["notes.txt", "randovango_20261101_120000.tar.gz.enc.part",
             "randovango_20261101_120000.tar.gz.enc", "randovango_20261102_120000.tar.gz.enc"]
    assert backup.archives_to_delete(names, keep=1) == ["randovango_20261101_120000.tar.gz.enc"]


def test_archives_to_delete_counts_icloud_placeholders():
    """Une archive qu'iCloud a remplacée par un repère « .nom.icloud » compte encore comme une version."""
    names = [".randovango_20261101_120000.tar.gz.enc.icloud",
             "randovango_20261102_120000.tar.gz.enc"]
    assert backup.archives_to_delete(names, keep=1) == [
        ".randovango_20261101_120000.tar.gz.enc.icloud"]


def test_copy_and_rotation_on_the_drive(tmp_path):
    """La copie arrive sur le drive sous son nom final, et le ménage ne garde que les versions voulues."""
    drive = tmp_path / "drive"
    drive.mkdir()
    for day in (1, 2):
        (drive / f"randovango_202611{day:02d}_120000.tar.gz.enc").write_text("ancienne")
    encrypted = tmp_path / "archive.tar.gz.enc"
    encrypted.write_text("nouvelle")
    backup.copy_to_destination(encrypted, drive, "randovango_20261119_120000.tar.gz.enc")
    removed = backup.remove_old_archives(drive, keep=2)
    assert removed == ["randovango_20261101_120000.tar.gz.enc"]
    assert sorted(path.name for path in drive.iterdir()) == [
        "randovango_20261102_120000.tar.gz.enc", "randovango_20261119_120000.tar.gz.enc"]


# --- Dumps et comptes de lignes ----------------------------------------------------------------

def test_is_complete_mysql_dump(tmp_path):
    """Un dump MySQL n'est accepté que s'il finit par « -- Dump completed »."""
    complete = tmp_path / "complet.sql"
    complete.write_text("CREATE TABLE spots (id INT);\n-- Dump completed on 2026-11-19\n")
    cut = tmp_path / "coupe.sql"
    cut.write_text("CREATE TABLE spots (id INT);\nINSERT INTO spots VALUES (1")
    assert backup.is_complete_mysql_dump(complete)
    assert not backup.is_complete_mysql_dump(cut)


def test_mysql_counts_query_and_its_answer():
    """Les lignes de chaque table MySQL sont comptées en une requête, et sa réponse est relue."""
    query = backup.mysql_counts_query(["spots", "restaurants"])
    assert query == ("SELECT 'spots', COUNT(*) FROM `spots` UNION ALL "
                     "SELECT 'restaurants', COUNT(*) FROM `restaurants`")
    assert backup.parse_tab_counts("spots\t1200\nrestaurants\t483\n") == {
        "spots": 1200, "restaurants": 483}


def test_copy_sqlite_keeps_every_account(tmp_path):
    """La copie de la base des comptes garde tous les comptes."""
    source = tmp_path / "rando_users.sqlite"
    make_sqlite(source, users=5)
    copy = tmp_path / "copie.sqlite"
    backup.copy_sqlite(source, copy)
    assert backup.count_sqlite_rows(copy) == {"users": 5}


# --- Restauration ------------------------------------------------------------------------------

def test_open_archive_gives_back_every_file(tmp_path):
    """Une archive chiffrée, rouverte avec son mot de passe, rend les dumps et les traces des passages."""
    work_dir, logs_dir = make_work_dir(tmp_path)
    archive_path = tmp_path / "archive.tar.gz"
    backup.build_archive(work_dir, logs_dir, archive_path)
    encrypted = tmp_path / "archive.tar.gz.enc"
    backup.encrypt_file(archive_path, encrypted, TEST_PASSWORD)

    target = tmp_path / "restauration"
    restore.open_archive(encrypted, target, TEST_PASSWORD)
    assert (target / "mysql.sql").read_text().endswith("-- Dump completed on 2026\n")
    assert (target / "logs" / "etl_osm.log").read_text() == "passage OSM\n"
    assert json.loads((target / "comptes.json").read_text())["mysql"] == {"spots": 0}


WRONG_PASSWORD_MESSAGE = "Déchiffrement impossible : mot de passe faux ou archive abîmée."


def test_open_archive_with_wrong_password_stops(tmp_path):
    """Avec un mauvais mot de passe, la restauration s'arrête sur le message prévu et rien n'est posé."""
    source = tmp_path / "archive.tar.gz"
    with tarfile.open(source, "w:gz"):
        pass
    encrypted = tmp_path / "archive.tar.gz.enc"
    backup.encrypt_file(source, encrypted, TEST_PASSWORD)
    with pytest.raises(SystemExit) as stop:
        restore.open_archive(encrypted, tmp_path / "restauration", "mauvais-mot-de-passe")
    assert stop.value.code == WRONG_PASSWORD_MESSAGE
    assert not list((tmp_path / "restauration").iterdir())


def test_open_archive_stops_when_openssl_accepts_a_wrong_password(tmp_path, monkeypatch):
    """Quand openssl « réussit » avec un mauvais mot de passe (CI du 20 nov. 2026), le message prévu s'affiche quand même."""
    def fake_decrypt(source, target, password):
        # Ce que rend openssl dans ce cas : des octets sans sens, sans erreur.
        target.write_bytes(bytes(range(256)) * 4)

    monkeypatch.setattr(backup, "decrypt_file", fake_decrypt)
    with pytest.raises(SystemExit) as stop:
        restore.open_archive(tmp_path / "archive.tar.gz.enc", tmp_path / "restauration", "mauvais")
    assert stop.value.code == WRONG_PASSWORD_MESSAGE
    assert not list((tmp_path / "restauration").iterdir())


def test_is_readable_archive_refuses_a_cut_archive(tmp_path):
    """Une archive .tar.gz coupée avant la fin n'est pas prise pour une archive intacte."""
    work_dir, logs_dir = make_work_dir(tmp_path)
    archive_path = tmp_path / "archive.tar.gz"
    backup.build_archive(work_dir, logs_dir, archive_path)
    assert restore.is_readable_archive(archive_path)
    cut = tmp_path / "coupee.tar.gz"
    cut.write_bytes(archive_path.read_bytes()[:-10])
    assert not restore.is_readable_archive(cut)


def test_is_safe_member_refuses_paths_that_leave_the_folder():
    """Un fichier d'archive qui sortirait du dossier de restauration est refusé."""
    assert restore.is_safe_member("logs/etl_osm.log")
    assert not restore.is_safe_member("../.env")
    assert not restore.is_safe_member("/etc/passwd")


def test_compare_counts_lists_only_the_differences():
    """La restauration d'essai signale les tables dont le nombre de lignes a changé, et elles seules."""
    expected = {"spots": 1200, "restaurants": 483, "decisions": 1948}
    actual = {"spots": 1200, "restaurants": 480, "cities": 148}
    assert restore.compare_counts(expected, actual) == [
        "cities : None à la sauvegarde, 148 restaurées",
        "decisions : 1948 à la sauvegarde, None restaurées",
        "restaurants : 483 à la sauvegarde, 480 restaurées",
    ]
    assert restore.compare_counts(expected, dict(expected)) == []
