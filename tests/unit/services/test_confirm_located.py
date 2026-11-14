"""Un lien Google Maps saisi à la main, avec sa position, confirme le service qui n'attendait que sa position."""
from services.supervision import services_review as review


class _Cursor:
    def __init__(self, signals):
        self.signals = signals

    def execute(self, sql, params=None):
        pass

    def fetchall(self):
        return self.signals


def _signal(reason="position introuvable", sheet=True):
    return {"id": 9, "detail": {"raison": reason, "fiche": {"genre": "crêperie"} if sheet else {}}}


def _confirmed(monkeypatch, signals, fields):
    """Rend ce que confirm_located répond, et les décisions qu'il a prises."""
    decisions = []
    monkeypatch.setattr(review, "decide_one", lambda cursor, tab, poi_id, action, note, by, months: decisions.append((tab, poi_id, action, by)))
    return review.confirm_located(_Cursor(signals), 32369, fields, "admin"), decisions


def test_a_maps_link_with_a_position_confirms_a_place_waiting_only_for_it(monkeypatch):
    """Galettes et Compagnie attendait pour « position introuvable » : le lien Google Maps saisi le confirme, sous le nom de l'admin."""
    done, decisions = _confirmed(monkeypatch, [_signal()], {"maps_url": "https://maps.app.goo.gl/x", "latitude": 48.07, "longitude": -4.19})
    assert done and decisions == [("confirmer", 32369, "valider_pepite", "admin")]


def test_a_maps_link_without_a_position_confirms_nothing(monkeypatch):
    """Un lien court, sans position lisible, ne confirme rien : la position reste introuvable."""
    done, decisions = _confirmed(monkeypatch, [_signal()], {"maps_url": "https://maps.app.goo.gl/x"})
    assert not done and decisions == []


def test_another_doubt_still_waits_for_the_human(monkeypatch):
    """Une alerte du registre, ou un lieu sans fiche préparée, attend toujours la décision humaine, même avec un lien Google Maps."""
    fields = {"maps_url": "https://maps.app.goo.gl/x", "latitude": 48.07, "longitude": -4.19}
    assert _confirmed(monkeypatch, [_signal("registre : enseigne fermée")], fields) == (False, [])
    assert _confirmed(monkeypatch, [_signal(sheet=False)], fields) == (False, [])
    assert _confirmed(monkeypatch, [], fields) == (False, [])
