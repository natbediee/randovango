"""
La notation des propositions de l'agent (services/decision_rating.py, carte #201) : les valeurs permises, et
où la note s'enregistre quand la superviseuse tranche un spot ou un service.
"""
import json
from unittest.mock import MagicMock

import pytest

from services import decision_rating
from services import poi_review_service as review
from services import supervision_service

# Le doute de doublon des tests de poi_review_service : A l'Aise Breizh Café (1201), proposé comme doublon de Fraya (1187).
BREIZH_DOUBT = {"id": 41, "poi_id": 1201, "source": "doublons", "signal_type": "doublon_service",
                "detail": json.dumps({"autre_id": 1187, "autre_nom": "Fraya", "distance_m": 15})}


def _ratings(cursor) -> list:
    """
    Les décisions enregistrées par le curseur : (lieu, décision, pertinence, raison). Les valeurs sont lues par le nom
    de leur colonne (decided_at vaut NOW(), sans paramètre) ; une requête sans colonne de note donne None.
    """
    rows = []
    for call in cursor.execute.call_args_list:
        sql = call[0][0]
        if "INSERT INTO decisions" in sql:
            columns = [name.strip() for name in sql.split("(", 1)[1].split(")", 1)[0].split(",")]
            values = dict(zip([name for name in columns if name != "decided_at"], call[0][1]))
            rows.append((values["objet_id"], values["decision"], values.get("pertinence"), values.get("raison")))
    return rows


@pytest.mark.parametrize("pertinence, raison", [
    (None, None), ("juste", None), ("a_corriger", None), ("fausse", "ferme_non_vu"), ("a_corriger", "autre"), ("", ""),
])
def test_a_known_rating_or_no_rating_is_accepted(pertinence, raison):
    """Une notation connue passe, et l'absence de notation aussi : noter une proposition reste facultatif."""
    decision_rating.check_rating(pertinence, raison)


@pytest.mark.parametrize("pertinence, raison", [
    ("parfaite", None), ("fausse", "trop_loin"), ("juste", "nom_adresse"), (None, "doublon_rate"), (["fausse"], None),
])
def test_an_unknown_or_inconsistent_rating_is_refused(pertinence, raison):
    """Une valeur inconnue, ou une raison sans proposition à corriger ou fausse, est refusée."""
    with pytest.raises(ValueError):
        decision_rating.check_rating(pertinence, raison)


def test_the_page_receives_every_allowed_value():
    """La page reçoit les libellés du serveur : elle ne peut proposer que ce que la route accepte."""
    labels = decision_rating.labels()
    assert list(labels["pertinences"]) == ["juste", "a_corriger", "fausse"]
    assert labels["raisons"]["pas_un_service"] == "pas un service pour le voyageur"
    assert labels["avec_raison"] == ["a_corriger", "fausse"]


def test_a_rated_spot_decision_records_its_rating(monkeypatch):
    """Garder un spot que l'agent voulait retirer, en notant sa proposition « fausse, preuve faible » : la note est enregistrée."""
    connection = MagicMock()
    cursor = connection.cursor.return_value
    cursor.fetchone.side_effect = [{"id": 31}, {"verifie": 0}]
    monkeypatch.setattr(supervision_service.MySQLUtils, "connect", lambda: connection)
    monkeypatch.setattr(supervision_service.MySQLUtils, "disconnect", lambda connection: None)
    supervision_service.decide(1368, "garder", "", "admin", None, "fausse", "preuve_faible")
    assert _ratings(cursor) == [(1368, "garder", "fausse", "preuve_faible")]


def test_an_unrated_spot_decision_is_recorded_as_before(monkeypatch):
    """Une décision sur un spot sans notation s'enregistre comme avant : pertinence et raison restent vides."""
    connection = MagicMock()
    cursor = connection.cursor.return_value
    cursor.fetchone.side_effect = [{"id": 31}, {"verifie": 0}]
    monkeypatch.setattr(supervision_service.MySQLUtils, "connect", lambda: connection)
    monkeypatch.setattr(supervision_service.MySQLUtils, "disconnect", lambda connection: None)
    supervision_service.decide(1368, "retirer", "", "admin")
    assert _ratings(cursor) == [(1368, "retirer", None, None)]


def test_a_rated_service_decision_records_its_rating():
    """Retirer une bijouterie classée supérette en notant la proposition « fausse, pas un service » : la note est enregistrée."""
    cursor = MagicMock()
    cursor.fetchall.side_effect = [
        [{"id": 8, "poi_id": 2686, "source": "osm", "signal_type": "lien_osm", "detail": json.dumps({"url": "https://a.fr"})}],
        [{"id": 8}],
    ]
    cursor.fetchone.return_value = {"url": None, "name": "Bijouterie Roudot", "masque": 0, "ferme_moment": 0,
                                    "statut_saison": None, "mois_ouverture": None}
    review.decide_one(cursor, "liens", 2686, "retirer", "", "admin", None, pertinence="fausse", raison="pas_un_service")
    assert _ratings(cursor) == [(2686, "retirer", "fausse", "pas_un_service")]


def test_keeping_one_duplicate_rates_the_decision_on_the_hidden_place():
    """Garder A l'Aise Breizh Café : la note de la proposition va sur la seule décision, celle de Fraya, le lieu masqué."""
    cursor = MagicMock()
    cursor.fetchall.side_effect = [[BREIZH_DOUBT], [{"id": 1201, "masque": 0}, {"id": 1187, "masque": 0}]]
    review.decide_one(cursor, "doublons", 1201, "garder_celui_ci", "", "admin", None, pertinence="juste")
    assert _ratings(cursor) == [(1187, "fusionner", "juste", None)]


def test_removing_both_duplicates_rates_only_the_card_place():
    """« Aucun des deux » écrit deux décisions, mais une carte vaut une note : seule celle du lieu de la carte la porte."""
    cursor = MagicMock()
    cursor.fetchall.side_effect = [[BREIZH_DOUBT], [BREIZH_DOUBT], [{"id": 41}], [{"id": 77}]]
    cursor.fetchone.side_effect = [{"url": None, "name": "A l'Aise Breizh Café", "masque": 0}, {"masque": 0}]
    review.decide_one(cursor, "doublons", 1201, "retirer_les_deux", "", "admin", None,
                      pertinence="a_corriger", raison="ferme_non_vu")
    assert _ratings(cursor) == [(1201, "retirer", "a_corriger", "ferme_non_vu"), (1187, "retirer", None, None)]
