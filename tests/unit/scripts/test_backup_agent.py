"""
Sauvegarde automatique, au plus une par jour dès que la machine est allumée
(scripts/backup_agent.py, issue #205). Ni launchd, ni Docker, ni notification : ils sont remplacés.
"""
import plistlib
from datetime import datetime
from pathlib import Path

import pytest

import backup
import backup_agent

NOW = datetime(2026, 11, 19, 15, 0, 0)


def test_archive_time_is_read_from_the_name():
    """La date d'une archive se lit dans son nom, même quand le drive n'en garde qu'un repère."""
    assert backup_agent.archive_time("randovango_20261119_154031.tar.gz.enc") == datetime(
        2026, 11, 19, 15, 40, 31)
    assert backup_agent.archive_time(".randovango_20261118_090000.tar.gz.enc.icloud") == datetime(
        2026, 11, 18, 9, 0, 0)
    assert backup_agent.archive_time("notes.txt") is None
    assert backup_agent.archive_time("randovango_20261119_154031.tar.gz.enc.part") is None


def test_latest_archive_time_takes_the_most_recent():
    """La dernière sauvegarde est la plus récente des archives du drive, les autres fichiers ignorés."""
    names = ["randovango_20261117_200000.tar.gz.enc", "notes.txt",
             "randovango_20261119_080000.tar.gz.enc", "randovango_20261118_200000.tar.gz.enc"]
    assert backup_agent.latest_archive_time(names) == datetime(2026, 11, 19, 8, 0, 0)
    assert backup_agent.latest_archive_time(["notes.txt"]) is None


def test_backup_is_due_after_24_hours_only():
    """Une sauvegarde est due sans archive ou au-delà de 24 heures, pas avant."""
    assert backup_agent.is_backup_due(None, NOW)
    assert backup_agent.is_backup_due(datetime(2026, 11, 18, 15, 0, 0), NOW)
    assert not backup_agent.is_backup_due(datetime(2026, 11, 18, 15, 0, 1), NOW)


@pytest.fixture
def no_side_effects(monkeypatch):
    """La sauvegarde et les notifications sont remplacées : on note seulement ce qui aurait eu lieu."""
    calls = {"backup": 0, "notifications": []}

    def fake_backup(project_dir, destination, keep, ask):
        calls["backup"] += 1
        return destination / "randovango_20261119_150000.tar.gz.enc"

    monkeypatch.setattr(backup, "backup", fake_backup)
    monkeypatch.setattr(backup_agent, "notify", calls["notifications"].append)
    return calls


def test_run_does_nothing_when_last_backup_is_recent(tmp_path, monkeypatch, no_side_effects):
    """Une sauvegarde de moins de 24 heures existe : le passage horaire ne fait rien."""
    (tmp_path / f"randovango_{datetime.now():%Y%m%d_%H%M%S}.tar.gz.enc").write_text("")
    monkeypatch.setattr(backup_agent, "databases_running", lambda: True)
    backup_agent.run(tmp_path, tmp_path)
    assert no_side_effects["backup"] == 0
    assert no_side_effects["notifications"] == []


def test_run_waits_when_databases_are_stopped(tmp_path, monkeypatch, no_side_effects):
    """Bases arrêtées : rien n'a pu changer, aucune sauvegarde ni alerte, nouvel essai l'heure suivante."""
    monkeypatch.setattr(backup_agent, "databases_running", lambda: False)
    backup_agent.run(tmp_path, tmp_path)
    assert no_side_effects["backup"] == 0
    assert no_side_effects["notifications"] == []


def test_run_backs_up_and_notifies_when_due(tmp_path, monkeypatch, no_side_effects):
    """Aucune archive récente et bases démarrées : la sauvegarde est faite et une notification le dit."""
    (tmp_path / "randovango_20261101_120000.tar.gz.enc").write_text("")
    monkeypatch.setattr(backup_agent, "databases_running", lambda: True)
    backup_agent.run(tmp_path, tmp_path)
    assert no_side_effects["backup"] == 1
    assert no_side_effects["notifications"] == [
        "Sauvegarde faite : randovango_20261119_150000.tar.gz.enc"]


def test_run_notifies_a_failed_backup(tmp_path, monkeypatch, no_side_effects):
    """Une sauvegarde qui échoue (mot de passe absent du trousseau) est signalée par une notification."""
    def failing_backup(project_dir, destination, keep, ask):
        raise SystemExit("Mot de passe introuvable dans le trousseau.")

    monkeypatch.setattr(backup, "backup", failing_backup)
    monkeypatch.setattr(backup_agent, "databases_running", lambda: True)
    with pytest.raises(SystemExit):
        backup_agent.run(tmp_path, tmp_path)
    assert no_side_effects["notifications"] == [
        "Sauvegarde échouée : Mot de passe introuvable dans le trousseau."]


def test_agent_description_runs_every_hour_and_at_login():
    """L'agent se lance à l'ouverture de la session puis toutes les heures, avec le PATH qui trouve docker."""
    project = Path("/projets/randovango")
    description = backup_agent.agent_description("/usr/bin/python3", project, "/opt/docker/bin:/usr/bin")
    assert description["RunAtLoad"] is True
    assert description["StartInterval"] == 3600
    assert description["EnvironmentVariables"] == {"PATH": "/opt/docker/bin:/usr/bin"}
    assert description["ProgramArguments"] == [
        "/usr/bin/python3", "-u", "/projets/randovango/scripts/backup_agent.py", "--lancer",
        "--projet", "/projets/randovango"]
    assert description["StandardOutPath"] == "/projets/randovango/logs/sauvegarde_automatique.log"
    # La description doit pouvoir s'écrire dans le format que lit launchd.
    assert plistlib.loads(plistlib.dumps(description)) == description
