"""Tests de services/supervision/decisions.py : la seule fonction qui enregistre une décision de la supervision."""
import json
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from services.supervision import decisions


def _inserted(cursor) -> dict:
    """Les valeurs passées à l'INSERT, rangées par nom de colonne (decided_at vaut NOW(), sans paramètre)."""
    sql, params = cursor.execute.call_args[0]
    columns = [name.strip() for name in sql.split("(", 1)[1].split(")", 1)[0].split(",")]
    return dict(zip([name for name in columns if name != "decided_at"], params))


@pytest.mark.parametrize("note, expected", [
    ("  Vu sur Street View  ", "Vu sur Street View"), ("", None), ("   ", None), (None, None), ("x" * 300, "x" * 255),
])
def test_the_note_is_trimmed_cut_and_empty_becomes_null(note, expected):
    """La note de l'admin perd ses espaces en trop, tient dans les 255 caractères de la colonne, et vide devient NULL."""
    assert decisions.clean_note(note) == expected


def test_a_service_decision_is_recorded_with_its_detail_in_json():
    """Un service retiré : la décision garde son type, son auteur, sa note nettoyée et l'état d'avant en JSON."""
    cursor = MagicMock()
    decisions.record_decision(cursor, "poi", 32498, "retirer", " fermé ", "admin",
                              {"file": "fermes", "avant": {"masque": 0}})
    values = _inserted(cursor)
    assert (values["objet_type"], values["objet_id"], values["decision"], values["note"], values["decided_by"]) == \
        ("poi", 32498, "retirer", "fermé", "admin")
    assert json.loads(values["detail"]) == {"file": "fermes", "avant": {"masque": 0}}
    assert (values["verification_id"], values["a_savoir_corrige"], values["pertinence"], values["raison"]) == \
        (None, None, None, None)


def test_a_spot_decision_keeps_its_verification_text_and_rating():
    """Un spot gardé : la vérification tranchée, le « À savoir » corrigé et la note de la proposition sont enregistrés."""
    cursor = MagicMock()
    decisions.record_decision(cursor, "spot", 1368, "garder", "", "admin", {"avant": {"verifie": True}},
                              verification_id=10, a_savoir_corrige="Parking payant l'été",
                              pertinence="fausse", raison="autre")
    values = _inserted(cursor)
    assert (values["verification_id"], values["a_savoir_corrige"], values["pertinence"], values["raison"]) == \
        (10, "Parking payant l'été", "fausse", "autre")


def test_accents_dates_and_decimals_in_the_detail_are_written_as_they_are():
    """L'état d'avant lu en base (accents, date, décimal) s'écrit en JSON sans erreur et reste lisible : « Crêperie »."""
    cursor = MagicMock()
    decisions.record_decision(cursor, "poi", 7, "autre_nom", None, "admin",
                              {"avant": {"name": "Crêperie", "updated": date(2026, 11, 14), "lat": Decimal("48.3")}})
    detail = _inserted(cursor)["detail"]
    assert "Crêperie" in detail
    assert json.loads(detail)["avant"] == {"name": "Crêperie", "updated": "2026-11-14", "lat": "48.3"}


def _stored(objet_type: str, objet_id: int, detail) -> MagicMock:
    """Une connexion dont la base rend cette décision encore active (ou aucune si objet_type vaut None)."""
    connection = MagicMock()
    row = None if objet_type is None else {"objet_type": objet_type, "objet_id": objet_id, "detail": detail}
    connection.cursor.return_value.fetchone.return_value = row
    return connection


def _cancel(monkeypatch, connection, decision_id: int = 55) -> list:
    """Lance l'annulation sur cette connexion et rend les requêtes passées, sans retours à la ligne."""
    monkeypatch.setattr(decisions.MySQLUtils, "connect", lambda: connection)
    monkeypatch.setattr(decisions.MySQLUtils, "disconnect", lambda connection: None)
    decisions.cancel_decision(decision_id)
    return [" ".join(call[0][0].split()) for call in connection.cursor.return_value.execute.call_args_list]


def test_a_service_decision_cancelled_from_the_spots_page_puts_the_service_back(monkeypatch):
    """
    Un numéro de décision de service reçu par l'annulation des spots (bascule de mode dans « Modifier ») : le service
    est remis comme avant et ses signaux rouverts, aucun spot n'est touché. Avant #186, la décision était seulement
    marquée annulée.
    """
    detail = json.dumps({"file": "fermes", "signal_ids": [31], "avant": {"masque": 0}})
    connection = _stored("poi", 48147, detail)
    queries = _cancel(monkeypatch, connection)
    assert "UPDATE poi SET masque = %s WHERE id = %s" in queries
    assert any(query.startswith("UPDATE poi_signals SET statut = 'a_relire'") for query in queries)
    assert not any(query.startswith("UPDATE spots") for query in queries)
    assert queries[-1] == "UPDATE decisions SET annulee_at = NOW() WHERE id = %s"
    connection.commit.assert_called_once()


def test_an_opening_decision_is_cancelled_by_the_same_function(monkeypatch):
    """Annuler une ouverture décidée remet les dates d'avant du spot, par la même fonction que les autres décisions."""
    detail = json.dumps({"avant": {"statut": "saison", "debut": None, "fin": None}})
    queries = _cancel(monkeypatch, _stored("ouverture", 1368, detail))
    assert any(query.startswith("UPDATE spots SET ouverture_statut") for query in queries)


def test_an_unknown_or_already_cancelled_decision_is_refused(monkeypatch):
    """Un double clic sur « annuler » : la décision déjà annulée est refusée, rien n'est changé ni validé."""
    connection = _stored(None, 0, None)
    with pytest.raises(ValueError):
        _cancel(monkeypatch, connection)
    connection.commit.assert_not_called()


def test_a_decision_of_an_unknown_type_is_refused_and_nothing_is_written(monkeypatch):
    """Une décision d'un type que la supervision ne sait pas défaire est refusée : rien n'est validé, tout est annulé."""
    connection = _stored("restaurant", 7, "{}")
    with pytest.raises(ValueError):
        _cancel(monkeypatch, connection)
    connection.commit.assert_not_called()
    connection.rollback.assert_called_once()
