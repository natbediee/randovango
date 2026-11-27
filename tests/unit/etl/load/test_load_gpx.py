"""
Le chargement d'une rando : le département, la région et le pays de sa ville (issue #318), et la rando enregistrée
ou retirée toujours avec son tracé (issue #285).
"""
from contextlib import contextmanager

import pytest

from etl.load import load_gpx

CHAMPAGNE = {"name": "Champagne", "insee": "17083", "latitude": 45.9, "longitude": -0.9,
             "department": "Charente-Maritime", "region": "Nouvelle-Aquitaine"}


def test_a_new_city_takes_its_department_from_the_state(monkeypatch) -> None:
    """Une ville créée par une rando prend son département et sa région à l'État, sans Nominatim qui refusait l'import du 23 novembre."""
    monkeypatch.setattr(load_gpx, "get_commune_details", lambda insee: CHAMPAGNE)
    monkeypatch.setattr(load_gpx, "get_admin_info_from_coordinates", lambda *args: (None, None, None))
    assert load_gpx.find_admin_info("17083", 45.9, -0.9) == ("Charente-Maritime", "Nouvelle-Aquitaine", "France")


def test_a_start_without_commune_still_asks_nominatim(monkeypatch) -> None:
    """Un départ sans commune française (hors de France) garde le département et le pays donnés par Nominatim."""
    monkeypatch.setattr(load_gpx, "get_commune_details", lambda insee: CHAMPAGNE)
    monkeypatch.setattr(load_gpx, "get_admin_info_from_coordinates", lambda *args: ("Gipuzkoa", "Euskadi", "España"))
    assert load_gpx.find_admin_info(None, 43.3, -1.9) == ("Gipuzkoa", "Euskadi", "España")


def test_the_state_silent_falls_back_on_nominatim(monkeypatch) -> None:
    """Si l'État ne répond pas, même après ses essais, Nominatim donne ce qu'il peut plutôt que rien."""
    monkeypatch.setattr(load_gpx, "get_commune_details", lambda insee: None)
    monkeypatch.setattr(load_gpx, "get_admin_info_from_coordinates", lambda *args: ("Charente-Maritime", "Nouvelle-Aquitaine", "France"))
    assert load_gpx.find_admin_info("17083", 45.9, -0.9) == ("Charente-Maritime", "Nouvelle-Aquitaine", "France")


def test_a_commune_read_with_the_gpx_is_not_asked_again(monkeypatch) -> None:
    """Une ville nouvelle dont la lecture du GPX a déjà donné le département ne redemande pas l'État au chargement (envoi de 240 randos, 25 novembre 2026)."""
    def not_asked(insee):
        raise AssertionError("l'État ne devait pas être redemandé")
    monkeypatch.setattr(load_gpx, "get_commune_details", not_asked)
    assert load_gpx.find_admin_info("17083", 45.9, -0.9, CHAMPAGNE) == ("Charente-Maritime", "Nouvelle-Aquitaine", "France")


def test_a_commune_read_without_department_is_asked_again(monkeypatch) -> None:
    """Une commune lue sans département (réponse partielle de l'État) est redemandée au chargement, comme avant."""
    monkeypatch.setattr(load_gpx, "get_commune_details", lambda insee: CHAMPAGNE)
    partial = {"name": "Champagne", "insee": "17083", "department": None, "region": None}
    assert load_gpx.find_admin_info("17083", 45.9, -0.9, partial) == ("Charente-Maritime", "Nouvelle-Aquitaine", "France")


# --- La rando et son tracé, ensemble ou pas du tout (issue #285) ---
# Ni MySQL ni MongoDB : une fausse connexion note ce qui est écrit et validé, une fausse collection garde les tracés.

TRACE_ID = "6560a1b2c3d4e5f6a7b8c9d0"
HIKE = {"name": "Tour de la pointe", "description": "", "start_lat": 48.36, "start_lon": -4.77, "distance_km": 8.2,
        "estimated_duration_h": 2.5, "denivele_m": 120, "difficulte": "facile", "points": [], "waypoints": []}


class FakeCursor:
    """Un curseur MySQL qui envoie ses requêtes à la fausse connexion."""
    def __init__(self, conn):
        self.conn, self.lastrowid, self.rowcount = conn, None, 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, query, params=None):
        self.conn.pending.append(query.split()[0])
        if query.lstrip().startswith("INSERT INTO hikes"):
            self.lastrowid = 42
        if query.lstrip().startswith("DELETE FROM hikes"):
            if self.conn.fail_delete:
                raise RuntimeError("la rando est dans un voyage")
            self.rowcount = 1

    def fetchone(self):
        return (1,) if self.conn.hike_in_mysql else None


class FakeConnection:
    """Une connexion MySQL : les requêtes attendent le commit, et un rollback les annule."""
    def __init__(self, hike_in_mysql=False, fail_delete=False):
        self.pending, self.committed, self.rolled_back = [], [], False
        self.hike_in_mysql, self.fail_delete = hike_in_mysql, fail_delete

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.committed += self.pending
        self.pending = []

    def rollback(self):
        self.pending, self.rolled_back = [], True


class FakeCollection:
    """La collection gpx_traces : garde les tracés écrits ; `fail` fait échouer l'écriture, comme un MongoDB arrêté."""
    def __init__(self, traces=None, fail=False):
        self.traces, self.fail = list(traces or []), fail

    def insert_one(self, doc):
        if self.fail:
            raise RuntimeError("MongoDB ne répond pas")
        self.traces.append({**doc, "_id": TRACE_ID})
        return type("Result", (), {"inserted_id": TRACE_ID})()

    def find_one(self, query):
        return next((t for t in self.traces if t["filename"] == query["filename"]), None)

    def delete_one(self, query):
        self.traces = [t for t in self.traces if str(t["_id"]) != str(query["_id"])]

    def delete_many(self, query):
        before = len(self.traces)
        self.traces = [t for t in self.traces if t["filename"] != query["filename"]]
        return type("Result", (), {"deleted_count": before - len(self.traces)})()


@pytest.fixture
def gpx_file(tmp_path):
    """Un fichier GPX déposé, que le chargement relit pour garder son contenu brut avec le tracé."""
    path = tmp_path / "tour.gpx"
    path.write_text("<gpx></gpx>", encoding="utf-8")
    return path


def test_a_hike_is_committed_only_with_its_trace(gpx_file) -> None:
    """Une rando dont le tracé s'écrit est validée dans MySQL, reliée à son tracé, et le tracé garde l'id de la rando."""
    conn, traces = FakeConnection(), FakeCollection()
    load_gpx.save_hike_with_trace(conn, traces, HIKE, str(gpx_file), source_id=1, city_id=2, verifie=1)
    assert conn.committed == ["INSERT", "UPDATE"]
    assert traces.traces[0]["hike_mysql_id"] == 42


def test_a_hike_whose_trace_fails_is_not_kept(gpx_file) -> None:
    """Si MongoDB refuse le tracé (conteneur arrêté, document de plus de 16 Mo), la rando n'est pas gardée et l'envoi échoue."""
    conn, traces = FakeConnection(), FakeCollection(fail=True)
    with pytest.raises(RuntimeError):
        load_gpx.save_hike_with_trace(conn, traces, HIKE, str(gpx_file), source_id=1, city_id=2, verifie=1)
    assert (conn.committed, conn.rolled_back, traces.traces) == ([], True, [])


def test_a_trace_written_before_a_failure_is_removed(gpx_file, monkeypatch) -> None:
    """Si MySQL échoue après l'écriture du tracé, le tracé est retiré : aucun tracé ne reste sans sa rando."""
    conn, traces = FakeConnection(), FakeCollection()
    def commit_fails():
        raise RuntimeError("MySQL a coupé la connexion")
    monkeypatch.setattr(conn, "commit", commit_fails)
    monkeypatch.setattr(load_gpx, "ObjectId", str)
    with pytest.raises(RuntimeError):
        load_gpx.save_hike_with_trace(conn, traces, HIKE, str(gpx_file), source_id=1, city_id=2, verifie=1)
    assert (conn.rolled_back, traces.traces) == (True, [])


def test_a_trace_left_without_hike_does_not_block_a_new_upload() -> None:
    """Un tracé resté seul après un échec est retiré, et le même fichier renvoyé se charge normalement."""
    traces = FakeCollection([{"_id": TRACE_ID, "filename": "tour.gpx"}])
    assert load_gpx.trace_already_loaded(FakeConnection(hike_in_mysql=False), traces, "tour.gpx") is False
    assert traces.traces == []


def test_a_hike_already_loaded_with_its_trace_is_refused() -> None:
    """Un fichier dont la rando et le tracé sont déjà en base reste refusé comme « déjà en base », et son tracé est gardé."""
    traces = FakeCollection([{"_id": TRACE_ID, "filename": "tour.gpx"}])
    assert load_gpx.trace_already_loaded(FakeConnection(hike_in_mysql=True), traces, "tour.gpx") is True
    assert len(traces.traces) == 1


@pytest.fixture
def fake_bases(monkeypatch):
    """Remplace les vraies bases du retrait d'une rando par une fausse connexion MySQL et une fausse collection."""
    def use(conn, traces):
        @contextmanager
        def open_cursor(**options):
            yield conn, conn.cursor()
        monkeypatch.setattr(load_gpx.MySQLUtils, "open_cursor", open_cursor)
        monkeypatch.setattr(load_gpx.MongoUtils, "connect", lambda: None)
        monkeypatch.setattr(load_gpx.MongoUtils, "get_collection", lambda name: traces)
    return use


def test_a_hike_is_deleted_with_its_trace(fake_bases) -> None:
    """Une rando retirée l'est avec son tracé, dans MySQL comme dans MongoDB."""
    conn, traces = FakeConnection(), FakeCollection([{"_id": TRACE_ID, "filename": "tour.gpx"}])
    fake_bases(conn, traces)
    assert load_gpx.delete_hike_with_trace("tour.gpx") == (1, 1)
    assert (conn.committed, traces.traces) == (["DELETE"], [])


def test_a_hike_stays_when_its_trace_cannot_be_deleted(fake_bases) -> None:
    """Si MongoDB ne répond pas au retrait, la rando reste en base avec son tracé, plutôt qu'un tracé sans rando."""
    conn, traces = FakeConnection(), FakeCollection()
    def mongo_down(query):
        raise RuntimeError("MongoDB ne répond pas")
    traces.delete_many = mongo_down
    fake_bases(conn, traces)
    with pytest.raises(RuntimeError):
        load_gpx.delete_hike_with_trace("tour.gpx")
    assert (conn.committed, conn.rolled_back) == ([], True)


def test_a_hike_in_a_trip_keeps_its_trace(fake_bases) -> None:
    """Une rando que MySQL refuse de retirer (elle est dans un voyage) garde son tracé."""
    conn, traces = FakeConnection(fail_delete=True), FakeCollection([{"_id": TRACE_ID, "filename": "tour.gpx"}])
    fake_bases(conn, traces)
    with pytest.raises(RuntimeError):
        load_gpx.delete_hike_with_trace("tour.gpx")
    assert len(traces.traces) == 1
