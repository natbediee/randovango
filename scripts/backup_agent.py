"""
Sauvegarde automatique des bases (issue #205) : au plus une par jour, dès que la machine est allumée.

Pourquoi : la machine de développement n'est pas un serveur, elle n'est pas toujours allumée. Une
sauvegarde à heure fixe serait sautée chaque fois qu'elle est éteinte à cette heure-là. On fait donc
l'inverse : le planificateur du système (launchd) lance ce script à l'ouverture de la session, puis
toutes les heures, et le script décide lui-même s'il y a quelque chose à faire :
- la dernière archive a moins de 24 heures : rien à faire ;
- les bases ne tournent pas : rien n'a pu changer, rien à faire (on réessaie l'heure suivante) ;
- sinon : sauvegarde complète par scripts/backup.py, puis une notification dit si elle a réussi.

Les passages des agents tournent sur cette même machine : quand elle est éteinte, aucune donnée
ne change. Dès qu'elle est allumée avec Docker, une sauvegarde de moins de 24 heures est garantie.

Utilisation (depuis le dossier du projet) :
    python3 scripts/backup_agent.py --installer   # une fois : inscrit l'agent auprès de launchd
    python3 scripts/backup_agent.py --retirer     # désinscrit l'agent
    python3 scripts/backup_agent.py --lancer      # ce que launchd lance toutes les heures
"""
from __future__ import annotations

import argparse
import os
import plistlib
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import backup

# Nom de l'agent pour launchd, et fichier qui le décrit (dossier des agents de la session).
AGENT_LABEL = "com.randovango.backup"
AGENT_FILE = Path.home() / "Library/LaunchAgents" / f"{AGENT_LABEL}.plist"

# Toutes les heures, launchd relance le script ; une sauvegarde est due au-delà de 24 heures.
CHECK_INTERVAL_SECONDS = 3600
MAX_AGE = timedelta(hours=24)


# --- Faut-il sauvegarder ? ---------------------------------------------------------------------

def archive_time(file_name: str) -> datetime | None:
    """La date d'une archive, lue dans son nom ; None si le fichier n'est pas une archive."""
    name = backup.visible_name(file_name)
    if not backup.ARCHIVE_PATTERN.match(name):
        return None
    return datetime.strptime(name, "randovango_%Y%m%d_%H%M%S.tar.gz.enc")


def latest_archive_time(file_names: list[str]) -> datetime | None:
    """La date de l'archive la plus récente parmi ces fichiers ; None s'il n'y en a aucune."""
    times = [moment for moment in map(archive_time, file_names) if moment is not None]
    return max(times) if times else None


def is_backup_due(latest: datetime | None, now: datetime) -> bool:
    """Vrai s'il n'y a aucune archive, ou si la dernière a plus de 24 heures."""
    return latest is None or now - latest >= MAX_AGE


def destination_files(destination: Path) -> list[str]:
    """Les noms des fichiers du dossier du drive (aucun si le dossier n'existe pas encore)."""
    return [path.name for path in destination.iterdir()] if destination.is_dir() else []


def databases_running() -> bool:
    """Vrai si les conteneurs MySQL et Mongo tournent ; faux si l'un est arrêté ou Docker éteint."""
    result = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", backup.MYSQL_CONTAINER,
         backup.MONGO_CONTAINER],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and result.stdout.split() == ["true", "true"]


# --- Lancement par launchd ---------------------------------------------------------------------

def notify(message: str) -> None:
    """Affiche une notification du système : la sauvegarde tourne sans terminal pour le dire."""
    text = message.replace('"', "'")
    subprocess.run(["osascript", "-e", f'display notification "{text}" with title "Randovango"'],
                   capture_output=True)


def run(project_dir: Path, destination: Path) -> None:
    """Ce que launchd lance toutes les heures : sauvegarde si elle est due, puis notification."""
    now = datetime.now()
    latest = latest_archive_time(destination_files(destination))
    if not is_backup_due(latest, now):
        print(f"{now:%d/%m %H:%M} : dernière sauvegarde le {latest:%d/%m à %H:%M}, rien à faire.")
        return
    if not databases_running():
        print(f"{now:%d/%m %H:%M} : bases arrêtées, rien n'a pu changer ; nouvel essai dans 1 h.")
        return
    try:
        final = backup.backup(project_dir, destination, backup.KEEP, ask=False)
    except (Exception, SystemExit) as error:
        # SystemExit aussi : backup.py s'arrête par sys.exit quand le trousseau n'a pas le mot de
        # passe ou qu'un dump est incomplet ; l'erreur doit être vue, pas seulement écrite au journal.
        notify(f"Sauvegarde échouée : {error}")
        raise
    notify(f"Sauvegarde faite : {final.name}")


# --- Inscription auprès de launchd -------------------------------------------------------------

def agent_description(python: str, project_dir: Path, path_variable: str) -> dict:
    """
    Le contenu du fichier qui décrit l'agent à launchd. Piège : launchd lance les programmes avec
    un PATH réduit, où la commande docker est introuvable ; on lui donne donc celui du terminal.
    """
    script = project_dir / "scripts" / "backup_agent.py"
    journal = project_dir / "logs" / "sauvegarde_automatique.log"
    return {
        "Label": AGENT_LABEL,
        # -u : les messages vont au journal tout de suite, sans attendre la fin du script.
        "ProgramArguments": [python, "-u", str(script), "--lancer", "--projet", str(project_dir)],
        "RunAtLoad": True,
        "StartInterval": CHECK_INTERVAL_SECONDS,
        "EnvironmentVariables": {"PATH": path_variable},
        "StandardOutPath": str(journal),
        "StandardErrorPath": str(journal),
    }


def session_domain() -> str:
    """Le domaine launchd de la session ouverte (gui/<numéro de l'utilisatrice>)."""
    return f"gui/{os.getuid()}"


def install(project_dir: Path) -> None:
    """Écrit la description de l'agent et l'inscrit auprès de launchd ; il se lance aussitôt."""
    (project_dir / "logs").mkdir(exist_ok=True)
    description = agent_description(sys.executable, project_dir.resolve(), os.environ["PATH"])
    AGENT_FILE.parent.mkdir(parents=True, exist_ok=True)
    # Un agent déjà inscrit est d'abord retiré, pour que la nouvelle description soit prise.
    subprocess.run(["launchctl", "bootout", session_domain(), str(AGENT_FILE)], capture_output=True)
    with open(AGENT_FILE, "wb") as file:
        plistlib.dump(description, file)
    subprocess.run(["launchctl", "bootstrap", session_domain(), str(AGENT_FILE)], check=True)
    print(f"Agent inscrit : {AGENT_FILE}")
    print(f"Journal : {description['StandardOutPath']}")


def uninstall() -> None:
    """Désinscrit l'agent et efface sa description : plus aucune sauvegarde automatique."""
    subprocess.run(["launchctl", "bootout", session_domain(), str(AGENT_FILE)], capture_output=True)
    AGENT_FILE.unlink(missing_ok=True)
    print("Agent retiré : plus de sauvegarde automatique.")


def parse_arguments() -> argparse.Namespace:
    """Lit les options de la ligne de commande."""
    parser = argparse.ArgumentParser(description="Sauvegarde automatique, au plus une par jour.")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--installer", action="store_true", help="inscrire l'agent auprès de launchd")
    action.add_argument("--retirer", action="store_true", help="désinscrire l'agent")
    action.add_argument("--lancer", action="store_true",
                        help="sauvegarder si la dernière archive a plus de 24 heures")
    parser.add_argument("--projet", type=Path, default=backup.PROJECT_DIR,
                        help="dossier du projet qui contient storage/ et logs/")
    return parser.parse_args()


if __name__ == "__main__":
    options = parse_arguments()
    if options.installer:
        install(options.projet)
    elif options.retirer:
        uninstall()
    else:
        run(options.projet, backup.DRIVE_DIR)
