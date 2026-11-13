import json

from services import poi_triage_service as triage


def signal(kind, source="osm", **detail):
    return {"id": 1, "signal_type": kind, "source": source, "detail": json.dumps(detail)}


def test_a_reported_closure_hides_the_place() -> None:
    """Une fermeture signalée par OSM ou par un agent, ou un lieu absent d'OSM, masque le service."""
    assert triage.must_hide([signal("fermeture_osm", "osm")])
    assert triage.must_hide([signal("absent_osm", "osm")])
    assert triage.must_hide([signal("fermeture_agent", "agent", type="definitive")])
    assert triage.must_hide([signal("fermeture_agent", "agent", type="reprise")])


def test_a_place_that_still_exists_stays_visible() -> None:
    """Un renommage ou une fermeture momentanée laisse le service visible."""
    assert not triage.must_hide([signal("renommage_osm", "osm")])
    assert not triage.must_hide([signal("fermeture_agent", "agent", type="momentanee")])


def test_only_checked_sites_and_tourism_pages_are_applied() -> None:
    """Seul le lien d'agent contrôlé qui mène au site du lieu ou à un office de tourisme est appliqué sans relecture."""
    assert triage.auto_link_allowed([signal("lien_agent", "agent", niveau="auto", type_page="site")])
    assert triage.auto_link_allowed([signal("lien_agent", "agent", niveau="auto", type_page="office_tourisme")])
    assert not triage.auto_link_allowed([signal("lien_agent", "agent", niveau="auto", type_page="facebook")])
    assert not triage.auto_link_allowed([signal("lien_agent", "agent", niveau="a_valider", type_page="site")])


def test_an_osm_link_needs_the_same_control() -> None:
    """Un lien d'OSM n'est appliqué que si le contrôle de la page a retrouvé le lieu."""
    assert triage.auto_link_allowed([signal("lien_osm", "osm", url="https://a.fr", controle="ok")])
    assert not triage.auto_link_allowed([signal("lien_osm", "osm", url="https://a.fr", controle="nom_absent")])
    assert not triage.auto_link_allowed([signal("lien_osm", "osm", url="https://a.fr")])


def test_an_osm_social_page_is_accepted_without_reading_it() -> None:
    """Une page sociale donnée par OSM, ou une page qui porte le téléphone du lieu, est acceptée sans être lue."""
    assert triage.auto_link_allowed([signal("lien_osm", "osm", url="https://www.facebook.com/a", controle="a_valider_social")])
    assert triage.auto_link_allowed([signal("lien_osm", "osm", url="https://a.fr", controle="ok_telephone")])


def test_an_agent_social_page_still_waits_for_a_human() -> None:
    """Une page sociale proposée par un agent attend toujours la décision d'un humain."""
    assert not triage.auto_link_allowed([signal("lien_agent", "agent", niveau="a_valider", type_page="facebook")])


def test_a_closure_without_another_name_removes_the_place() -> None:
    """Une fermeture définitive sans autre nom retire le service."""
    assert triage.must_remove([signal("absent_osm")])
    assert triage.must_remove([signal("fermeture_agent", type="definitive")])


def test_a_new_name_or_a_closure_for_now_waits_for_a_human() -> None:
    """Un nouveau nom, une reprise ou une fermeture momentanée attend la décision d'un humain."""
    assert not triage.must_remove([signal("fermeture_osm"), signal("renommage_osm", nom_osm="La Cale")])
    assert not triage.must_remove([signal("fermeture_agent", type="reprise", autre_nom="Le Neuf")])
    assert not triage.must_remove([signal("fermeture_agent", type="momentanee")])


def test_what_the_restaurant_agent_made_useless_has_no_follow_up() -> None:
    """Là où l'agent des restaurants est passé, les signaux d'un restaurant sans fiche sont classés sans suite ; ailleurs, et pour les autres services, ils restent."""
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
    """Là où l'agent des commerces est passé, le lien d'un commerce sans fiche est classé sans suite (« Au jardin », Marseille)."""
    au_jardin = {"poi_id": 6377, "address": "52 Boulevard Chave, 13005 Marseille"}
    chains = [({"restaurant"}, set(), set()), ({"convenience"}, {10}, {"13005"})]
    assert triage.without_follow_up("liens", au_jardin, chains, {6377: {"convenience"}})


def test_a_link_already_refused_or_removed_is_not_proposed_again() -> None:
    """Un lien déjà refusé ou retiré pour ce lieu n'est pas proposé une seconde fois (« Au jardin », Marseille)."""
    signal = {"signal_type": "lien_osm", "detail": {"url": "https://www.aujardin-marseille.com/"}}
    judged = {(6377, triage.link_key("http://aujardin-marseille.com"))}
    assert triage.already_judged([signal], 6377, judged) and not triage.already_judged([signal], 1, judged)


def test_a_domain_that_no_longer_exists_is_a_dead_link(monkeypatch) -> None:
    """Un domaine qui n'existe plus fait un lien mort."""
    def no_domain(host, port):
        raise triage.socket.gaierror("introuvable")
    monkeypatch.setattr(triage.socket, "getaddrinfo", no_domain)
    assert triage._control_osm_link({"detail": {"url": "http://aujardin-marseille.com"}}) == "lien_mort"


def test_every_family_of_shop_sheets_is_a_chain_of_its_own() -> None:
    """Le tri connaît les supermarchés : leurs fiches font une chaîne à part, comme les cafés, et ne comptent pas pour les commerces."""
    by_services = {services: sql for services, sql in triage.CHAINS}
    assert "c.categorie = 'supermarche'" in by_services[triage.OWN_TAB["supermarche"]] and "supermarket" in triage.OWN_TAB["supermarche"]
    assert "c.categorie = 'cafe'" in by_services[triage.OWN_TAB["cafe"]]
    assert "NOT IN ('cafe', 'supermarche')" in by_services[triage.COMMERCE_SERVICES]


def test_a_supermarket_without_a_sheet_has_no_follow_up_anywhere() -> None:
    """Les signaux d'un supermarché d'OSM sans fiche sont classés sans suite partout, même où l'agent n'est jamais passé : l'étape 4 ne le montre plus (Leclerc de Guilers) ; ceux d'un supermarché qui a sa fiche suivent la règle des fiches."""
    guilers = {"poi_id": 8277, "address": "Rue du Tumulus, 29820 Guilers"}
    lidl = {"poi_id": 11, "address": "Rue du Pont de Bois, 29290 Saint-Renan"}
    chains = [({"convenience"}, {10}, {"29217"}), ({"supermarket"}, {11}, {"29290"})]
    categories = {8277: {"supermarket"}, 11: {"supermarket"}}
    assert triage.without_follow_up("fermetures", guilers, chains, categories)
    assert triage.without_follow_up("liens", lidl, chains, categories)
    assert not triage.without_follow_up("fermetures", lidl, chains, categories)


def _sort_stations(monkeypatch, trial=False):
    from unittest.mock import MagicMock
    connection = MagicMock()
    cursor = connection.cursor.return_value
    cursor.rowcount = 1
    monkeypatch.setattr(triage.MySQLUtils, "connect", lambda: connection)
    monkeypatch.setattr(triage.MySQLUtils, "disconnect", lambda c: None)
    return triage.hide_doubtful_stations(trial=trial), connection, [call.args for call in cursor.execute.call_args_list]


def test_a_doubtful_station_is_hidden_until_someone_looks(monkeypatch):
    """Une station avec un signal des carburants à relire est masquée : dans le doute, on ne l'affiche pas."""
    summary, connection, (hide, _) = _sort_stations(monkeypatch)
    assert "SET p.masque = 1" in hide[0] and "statut = 'a_relire'" in hide[0]
    assert hide[1] == ("carburants_osm", "carburants_etat")
    assert summary == {"masquees": 1, "reaffichees": 1}
    connection.commit.assert_called_once()


def test_a_station_back_to_normal_is_shown_again_unless_removed_by_hand(monkeypatch):
    """Une station qui déclare de nouveau revient sans relecture ; une station retirée ou fusionnée à la main reste masquée."""
    _, _, (_, show) = _sort_stations(monkeypatch)
    assert "SET p.masque = 0" in show[0] and "NOT EXISTS (SELECT 1 FROM poi_signals" in show[0]
    assert "d.annulee_at IS NULL" in show[0]
    assert show[1] == ("prix-carburants", "poi", "retirer", "fusionner")


def test_a_trial_sort_of_stations_writes_nothing(monkeypatch):
    """L'essai compte les stations à masquer et à réafficher sans rien écrire."""
    _, connection, _ = _sort_stations(monkeypatch, trial=True)
    connection.rollback.assert_called_once()
    connection.commit.assert_not_called()
