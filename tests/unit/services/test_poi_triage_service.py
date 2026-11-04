import json

from services import poi_triage_service as triage


def signal(kind, source="osm", **detail):
    return {"id": 1, "signal_type": kind, "source": source, "detail": json.dumps(detail)}


def test_a_reported_closure_hides_the_place() -> None:
    assert triage.must_hide([signal("fermeture_osm", "osm")])
    assert triage.must_hide([signal("absent_osm", "osm")])
    assert triage.must_hide([signal("fermeture_agent", "agent", type="definitive")])
    assert triage.must_hide([signal("fermeture_agent", "agent", type="reprise")])


def test_a_place_that_still_exists_stays_visible() -> None:
    assert not triage.must_hide([signal("renommage_osm", "osm")])
    assert not triage.must_hide([signal("fermeture_agent", "agent", type="momentanee")])


def test_only_checked_sites_and_tourism_pages_are_applied() -> None:
    assert triage.auto_link_allowed([signal("lien_agent", "agent", niveau="auto", type_page="site")])
    assert triage.auto_link_allowed([signal("lien_agent", "agent", niveau="auto", type_page="office_tourisme")])
    assert not triage.auto_link_allowed([signal("lien_agent", "agent", niveau="auto", type_page="facebook")])
    assert not triage.auto_link_allowed([signal("lien_agent", "agent", niveau="a_valider", type_page="site")])


def test_an_osm_link_needs_the_same_control() -> None:
    assert triage.auto_link_allowed([signal("lien_osm", "osm", url="https://a.fr", controle="ok")])
    assert not triage.auto_link_allowed([signal("lien_osm", "osm", url="https://a.fr", controle="nom_absent")])
    assert not triage.auto_link_allowed([signal("lien_osm", "osm", url="https://a.fr")])


def test_an_osm_social_page_is_accepted_without_reading_it() -> None:
    assert triage.auto_link_allowed([signal("lien_osm", "osm", url="https://www.facebook.com/a", controle="a_valider_social")])
    assert triage.auto_link_allowed([signal("lien_osm", "osm", url="https://a.fr", controle="ok_telephone")])


def test_an_agent_social_page_still_waits_for_a_human() -> None:
    assert not triage.auto_link_allowed([signal("lien_agent", "agent", niveau="a_valider", type_page="facebook")])
