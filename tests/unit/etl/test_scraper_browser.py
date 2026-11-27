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
