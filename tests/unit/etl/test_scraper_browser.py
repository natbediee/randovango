"""
Le navigateur qui lit la source des spots (etl/extract/scraper_p4n.py, issue #333). Cas réel du 26 novembre 2026 :
un passage coupé net a laissé son Chrome ouvert sur le profil fixe que tous partageaient, et chaque Chrome suivant
s'est fermé aussitôt ; 197 passages ont échoué avec un message qui accusait la ville ou la page.
Ni navigateur, ni réseau : Chrome et la recherche de la ville sont remplacés.
"""
import pytest
from selenium.common.exceptions import SessionNotCreatedException

from etl.extract import scraper_p4n
from etl.extract.scraper_p4n import BrowserNotStarted


def test_each_browser_gets_its_own_profile(monkeypatch):
    """Le navigateur est lancé sans profil fixe : un Chrome resté ouvert ne prend plus le profil des suivants."""
    launched = []
    monkeypatch.setattr(scraper_p4n.webdriver, "Chrome", lambda service, options: launched.append(options) or "chrome")
    assert scraper_p4n.create_driver() == "chrome"
    assert not any(argument.startswith("--user-data-dir") for argument in launched[0].arguments)


def test_a_browser_that_does_not_start_says_so(monkeypatch):
    """Un Chrome qui se ferme aussitôt lève BrowserNotStarted, avec le message de Chrome."""
    def refuse(service, options):
        raise SessionNotCreatedException("Chrome failed to start: exited normally.")
    monkeypatch.setattr(scraper_p4n.webdriver, "Chrome", refuse)
    with pytest.raises(BrowserNotStarted, match="Chrome failed to start"):
        scraper_p4n.create_driver()


def test_the_scraper_passes_on_a_browser_that_does_not_start(monkeypatch):
    """La lecture d'une ville ne cache pas un navigateur qui ne démarre pas sous un « None » de page illisible."""
    monkeypatch.setattr(scraper_p4n, "get_city_center", lambda name: (48.36, -4.77))

    def refuse(is_headless):
        raise BrowserNotStarted("le navigateur ne démarre pas (profil pris)")
    monkeypatch.setattr(scraper_p4n, "create_driver", refuse)
    with pytest.raises(BrowserNotStarted):
        scraper_p4n.run_p4n_scraper("Le Conquet")


# Les processus d'un conteneur, comme les donne ps : un passage coupé net (son Python mort, son chromedriver et son
# Chrome rattachés au n° 1) et une vérification des spots vivante (Python n° 50, son chromedriver, son Chrome et une
# page de ce Chrome). Le cas des villes 607 et 608, le 27 novembre 2026.
PS_LINES = """
    1     0 docker-init     /sbin/docker-init -- uvicorn main:app
   50     1 python3.12      python3.12 -m agents.verify_spots
  101     1 chromedriver    /usr/bin/chromedriver --port=111
  102   101 chromium        /usr/lib/chromium/chromium --user-data-dir=/tmp/org.chromium.Chromium.MORT
  103   102 chromium        /usr/lib/chromium/chromium --type=renderer
  201    50 chromedriver    /usr/bin/chromedriver --port=222
  202   201 chromium        /usr/lib/chromium/chromium --user-data-dir=/tmp/org.chromium.Chromium.VIVANT
  203   202 chromium        /usr/lib/chromium/chromium --type=renderer
"""


def fake_container(monkeypatch, tmp_path):
    """Un conteneur de test : Chromium installé, les processus de PS_LINES, et leurs profils dans un /tmp à part."""
    dead, alive = tmp_path / "org.chromium.Chromium.MORT", tmp_path / "org.chromium.Chromium.VIVANT"
    old = tmp_path / "selenium_chrome_profile"
    for profile in (dead, alive, old):
        profile.mkdir()
    lines = PS_LINES.replace("/tmp/", f"{tmp_path}/")
    killed = []
    monkeypatch.setattr(scraper_p4n.os.path, "exists", lambda path: True)
    monkeypatch.setattr(scraper_p4n.subprocess, "run",
                        lambda command, capture_output, text: type("Result", (), {"stdout": lines})())
    monkeypatch.setattr(scraper_p4n.os, "kill", lambda pid, sig: killed.append(pid))
    monkeypatch.setattr(scraper_p4n, "LEFTOVER_PROFILES",
                        (str(tmp_path / "org.chromium.Chromium.*"), str(old)))
    return killed, dead, alive, old


def test_leftover_browsers_are_closed_and_their_profiles_erased(monkeypatch, tmp_path):
    """Le chromedriver et le Chrome d'un passage coupé net sont fermés, avec leurs pages, et leur profil est effacé de /tmp."""
    killed, dead, alive, old = fake_container(monkeypatch, tmp_path)
    scraper_p4n.close_leftover_browsers()
    assert sorted(killed) == [101, 102, 103]
    assert not dead.exists() and not old.exists()


def test_a_running_verification_keeps_its_browser(monkeypatch, tmp_path):
    """Une vérification des spots en cours garde son Chrome et son profil quand une lecture de la source démarre (villes 607 et 608, #350)."""
    killed, dead, alive, old = fake_container(monkeypatch, tmp_path)
    scraper_p4n.close_leftover_browsers()
    assert not {50, 201, 202, 203} & set(killed)
    assert alive.exists()


def test_only_browsers_attached_to_the_first_process_are_orphans():
    """Un orphelin est un navigateur rattaché au processus n° 1, avec ce qu'il a lancé ; le Python lui-même n'en est pas un."""
    processes = [{"pid": 1, "ppid": 0, "name": "docker-init", "args": ""},
                 {"pid": 50, "ppid": 1, "name": "python3.12", "args": ""},
                 {"pid": 101, "ppid": 1, "name": "chromedriver", "args": ""},
                 {"pid": 102, "ppid": 101, "name": "chromium", "args": ""},
                 {"pid": 201, "ppid": 50, "name": "chromedriver", "args": ""}]
    assert scraper_p4n.orphan_browsers(processes) == {101, 102}


def test_outside_the_container_no_browser_is_closed(monkeypatch):
    """Sans Chromium installé (sur le Mac par exemple), aucun navigateur n'est fermé : le Chrome de l'utilisatrice reste."""
    killed = []
    monkeypatch.setattr(scraper_p4n.os.path, "exists", lambda path: False)
    monkeypatch.setattr(scraper_p4n.subprocess, "run", lambda *args, **kwargs: killed.append(args))
    monkeypatch.setattr(scraper_p4n.os, "kill", lambda pid, sig: killed.append(pid))
    scraper_p4n.close_leftover_browsers()
    assert killed == []
