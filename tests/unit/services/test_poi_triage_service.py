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


def test_a_closure_without_another_name_removes_the_place() -> None:
    assert triage.must_remove([signal("absent_osm")])
    assert triage.must_remove([signal("fermeture_agent", type="definitive")])


def test_a_new_name_or_a_closure_for_now_waits_for_a_human() -> None:
    assert not triage.must_remove([signal("fermeture_osm"), signal("renommage_osm", nom_osm="La Cale")])
    assert not triage.must_remove([signal("fermeture_agent", type="reprise", autre_nom="Le Neuf")])
    assert not triage.must_remove([signal("fermeture_agent", type="momentanee")])


def test_what_the_restaurant_agent_made_useless_has_no_follow_up() -> None:
    hidden = {"poi_id": 1, "address": "3 rue du Port, 29830 Ploudalmézeau"}
    elsewhere = {"poi_id": 2, "address": "1 place, 22000 Saint-Brieuc"}
    checked = {"poi_id": 3, "address": "4 rue du Port, 29830 Ploudalmézeau"}
    shop = {"poi_id": 4, "address": "5 rue du Port, 29830 Ploudalmézeau"}
    chains = [({"restaurant"}, {3}, {"29830"}), ({"bakery"}, set(), set())]
    categories = {1: {"restaurant"}, 2: {"restaurant"}, 3: {"restaurant"}, 4: {"bakery"}}
    args = (chains, categories)
    assert triage.without_follow_up("liens", hidden, *args) and triage.without_follow_up("fermetures", hidden, *args)
    assert not triage.without_follow_up("liens", elsewhere, *args)
    assert triage.without_follow_up("saison", checked, *args) and not triage.without_follow_up("fermetures", checked, *args)
    assert not triage.without_follow_up("liens", shop, *args)


def test_a_shop_without_a_sheet_where_the_shop_agent_went_has_no_follow_up() -> None:
    au_jardin = {"poi_id": 6377, "address": "52 Boulevard Chave, 13005 Marseille"}
    chains = [({"restaurant"}, set(), set()), ({"convenience"}, {10}, {"13005"})]
    assert triage.without_follow_up("liens", au_jardin, chains, {6377: {"convenience"}})


def test_a_link_already_refused_or_removed_is_not_proposed_again() -> None:
    signal = {"signal_type": "lien_osm", "detail": {"url": "https://www.aujardin-marseille.com/"}}
    judged = {(6377, triage.link_key("http://aujardin-marseille.com"))}
    assert triage.already_judged([signal], 6377, judged) and not triage.already_judged([signal], 1, judged)


def test_a_domain_that_no_longer_exists_is_a_dead_link(monkeypatch) -> None:
    def no_domain(host, port):
        raise triage.socket.gaierror("introuvable")
    monkeypatch.setattr(triage.socket, "getaddrinfo", no_domain)
    assert triage._control_osm_link({"detail": {"url": "http://aujardin-marseille.com"}}) == "lien_mort"
