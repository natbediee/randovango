import json

import pytest

from services import poi_review_service as review


def signal(kind, source="osm", **detail):
    return {"id": 1, "signal_type": kind, "source": source, "detail": json.dumps(detail)}


POI = {"id": 7, "name": "Mary Stuart", "address": "66 Avenue de la Mer", "service": "Restaurant", "url": None}


def test_a_takeover_proposes_to_rename_with_every_source() -> None:
    signals = [signal("fermeture_osm", "osm", nom_osm=None),
               signal("fermeture_agent", "agent", type="reprise", citation="clap de fin", autre_nom="La Petite Folie", page="https://presse.fr/a")]

    card = review.build_card("fermetures", POI, signals)

    assert card["new_name"] == "La Petite Folie"
    assert card["actions"] == ["renommer", "retirer", "garder"]
    assert card["signal"] == "Fermeture signalée"
    assert [proof["source"] for proof in card["preuves"]] == ["Agent", "OSM"]
    assert "clap de fin" in card["preuves"][0]["texte"]
    assert card["link"] == "https://presse.fr/a"


def test_an_osm_rename_proposes_its_name() -> None:
    assert review.build_card("fermetures", POI, [signal("renommage_osm", "osm", nom_osm="Kairos")])["new_name"] == "Kairos"


def test_a_temporary_closure_can_be_recorded() -> None:
    card = review.build_card("fermetures", POI, [signal("fermeture_agent", "agent", type="momentanee", citation="Fermeture temporaire")])
    assert "fermer_moment" in card["actions"]


def test_checked_link_goes_to_the_batch_and_social_does_not() -> None:
    checked = review.build_card("liens", POI, [signal("lien_agent", "agent", url="https://a.fr", type_page="site", verdict="ok", niveau="auto")])
    social = review.build_card("liens", POI, [signal("lien_agent", "agent", url="https://facebook.com/a", type_page="facebook",
                                                     verdict="a_valider_social", niveau="a_valider")])
    assert checked["auto"] is True
    assert social["auto"] is False


def test_the_agent_link_comes_before_the_osm_link() -> None:
    card = review.build_card("liens", POI, [signal("lien_osm", "osm", url="https://osm.fr"),
                                            signal("lien_agent", "agent", url="https://agent.fr", verdict="ok", niveau="auto")])
    assert card["url"] == "https://agent.fr"


def test_another_name_is_offered_only_when_the_page_shows_it() -> None:
    other = review.build_card("liens", POI, [signal("lien_agent", "agent", url="https://a.fr", verdict="a_valider_nom",
                                                    niveau="a_valider", autre_nom="Le Protis")])
    same = review.build_card("liens", POI, [signal("lien_agent", "agent", url="https://a.fr", verdict="ok", niveau="auto", autre_nom="Trebor")])
    assert other["actions"][0] == "valider_lien_nom"
    assert same["actions"] == ["valider_lien", "refuser_lien"]


def test_season_from_osm_gives_the_months() -> None:
    card = review.build_card("saison", POI, [signal("saison_osm", "osm", mois=["Apr", "May"], opening_hours="Apr-May")])
    assert card["months"] == [3, 4]
    assert card["statut"] == "confirmee"


def test_applied_fields_take_the_link_from_the_signal() -> None:
    card = {"url": "https://a.fr", "autre_nom": "Le Protis", "new_name": "La Petite Folie"}
    assert review.applied_fields("valider_lien", card, None) == {"url": "https://a.fr"}
    assert review.applied_fields("valider_lien_nom", card, None) == {"url": "https://a.fr", "name": "Le Protis"}
    assert review.applied_fields("renommer", card, None) == {"name": "La Petite Folie", "masque": 0}
    assert review.applied_fields("retirer", card, None) == {"masque": 1}
    assert review.applied_fields("retirer_lien", card, None) == {"url": None}
    assert review.applied_fields("garder", card, None) == {"masque": 0}
    assert review.applied_fields("refuser_lien", card, None) == {}


def test_season_without_months_stays_probable() -> None:
    fields = review.applied_fields("valider_saison", {}, [])
    assert fields["statut_saison"] == "probable"
    assert json.loads(fields["mois_ouverture"]) == []


def test_season_months_are_validated() -> None:
    fields = review.applied_fields("valider_saison", {}, [8, 3, 3, 99, "x"])
    assert fields["statut_saison"] == "confirmee"
    assert json.loads(fields["mois_ouverture"]) == [3, 8]


def test_only_links_can_be_decided_in_batch() -> None:
    with pytest.raises(ValueError):
        review.decide("fermetures", [1, 2], "retirer", "", "admin")
    with pytest.raises(ValueError):
        review.decide("liens", [1], "inconnue", "", "admin")


def test_every_action_has_its_wording() -> None:
    assert set(review.ACTIONS) == set(review.ACTION_LABELS) == set(review.ACTION_BUTTONS)
    assert set(review.APPLIED_COLUMNS) >= {"url", "name", "masque"}
