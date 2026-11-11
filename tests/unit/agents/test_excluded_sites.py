"""Les sites exclus ne sont jamais ouverts par le code, quoi que l'agent réponde."""
import pytest

from agents import find_restaurants, find_service_links, pepite_common
from agents.pepite_common import EXCLUDED_SITES_PROMPT, is_excluded_site


@pytest.mark.parametrize("url", [
    "https://www.tripadvisor.fr/Restaurant_Review-g1.html",
    "https://guide.michelin.com/fr/fr/bretagne/restaurant/x",
    "https://fr.restaurantguru.com/x",
    "https://restaurant-guru.in/x",
    "https://www.thefork.fr/restaurant/x",
    "https://www.lafourchette.com/x",
    "https://www.petitfute.com/x",
    "https://fr.gaultmillau.com/x",
    "https://www.pagesjaunes.fr/pros/1",
    "https://www.google.com/maps/place/x",
    "https://maps.app.goo.gl/abc",
    "www.TripAdvisor.com/x",
])
def test_excluded_sites_are_recognised(url):
    assert is_excluded_site(url)


@pytest.mark.parametrize("url", [
    "https://www.iroise-bretagne.bzh/restaurant/x/",
    "https://cafekonk.fr/",
    "https://le-michelin-du-port.fr/",
    "https://www.facebook.com/x",
    "https://www.example.fr/tripadvisor",
])
def test_other_sites_are_not_excluded(url):
    assert not is_excluded_site(url)


def _no_network(*args, **kwargs):
    raise AssertionError("le code a ouvert un site exclu")


def test_code_never_opens_an_excluded_site(monkeypatch):
    monkeypatch.setattr(find_service_links.requests, "get", _no_network)
    monkeypatch.setattr(pepite_common.requests, "get", _no_network)
    url = "https://www.tripadvisor.fr/x"
    assert find_service_links.read_page(url)["erreur"] == "site_exclu"
    assert pepite_common.link_status(url) is None
    assert find_service_links.citation_found("une phrase", url) is None


def test_excluded_link_is_refused_as_proof(monkeypatch):
    monkeypatch.setattr(find_service_links.requests, "get", _no_network)
    place = {"name": "Riboul", "commune": "Plougonvelin", "cp": "29217", "telephone": None}
    row = {"liens": [{"url": "https://guide.michelin.com/x", "type_page": "guide"}]}
    links = find_service_links.check_links_of(row, place)
    assert links[0]["verdict"] == "site_exclu"
    assert find_service_links.best_link(links) is None


def test_every_restaurant_prompt_names_the_excluded_sites():
    for prompt in (find_restaurants.SYSTEM_PROMPT, find_restaurants.SEASON_PROMPT, find_restaurants.ANALYSIS_PROMPT,
                   find_restaurants.PROOF_PROMPT, find_service_links.SYSTEM_PROMPT):
        assert EXCLUDED_SITES_PROMPT in prompt
