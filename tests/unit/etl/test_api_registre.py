from etl.extract import api_registre
from etl.extract.api_registre import add_establishment, place_name


def _register():
    return {"actifs": [], "enseignes_fermees": [], "radies": []}


def _place(state="A", **fields):
    return {"etat_administratif": state, "adresse": "1 QUAI", "activite_principale": "56.10A", "date_creation": "2024-11-28", **fields}


COMPANY = {"nature_juridique": "5710", "nom_raison_sociale": "SARL AR DAGENTA"}
PERSON = {"nature_juridique": "1000", "nom_complet": "Prénom NOM"}


def test_the_sign_comes_first():
    assert place_name({"liste_enseignes": ["NOUS"]}, COMPANY) == "NOUS"


def test_a_company_gives_its_name():
    assert place_name({}, COMPANY) == "SARL AR DAGENTA"


def test_a_person_name_is_never_kept():
    assert place_name({}, PERSON) is None


def test_a_strike_off_leaves_the_active_list():
    register = _register()
    add_establishment(register, _place(), COMPANY, {"famille": "Radiations", "date": "2023-02-24", "jugement": None}, "2021")
    assert register["actifs"] == [] and register["radies"][0]["radie_le"] == "2023-02-24"


def test_a_liquidation_stays_active_with_its_signal():
    register = _register()
    notice = {"famille": "Procédures collectives", "date": "2026-09-27", "jugement": "Jugement d'ouverture de liquidation judiciaire"}
    add_establishment(register, _place(), COMPANY, notice, "2021")
    assert "liquidation" in register["actifs"][0]["derniere_annonce"]


def test_only_a_recent_closed_sign_is_kept():
    register = _register()
    add_establishment(register, _place("F", liste_enseignes=["LA MARINA"], date_fermeture="2026-03-12"), COMPANY, {}, "2021")
    add_establishment(register, _place("F", liste_enseignes=["TROP VIEUX"], date_fermeture="2006-01-01"), COMPANY, {}, "2021")
    assert [line["nom"] for line in register["enseignes_fermees"]] == ["LA MARINA"]


def test_an_unreadable_register_does_not_stop_the_search(monkeypatch):
    def broken(*args):
        raise api_registre.requests.ConnectionError("hors ligne")

    monkeypatch.setattr(api_registre, "commune_code", broken)
    assert api_registre.load_register({"name": "X", "latitude": 48, "longitude": -4}) is None


def test_only_this_commune_and_these_activities_are_read(monkeypatch):
    """Une société peut avoir des établissements ailleurs, ou une autre activité. Une annonce par société suffit."""
    pages = {1: {"total_pages": 2, "results": [{"siren": "1", "nature_juridique": "5710", "nom_raison_sociale": "SARL A", "matching_etablissements": [
                 _place(commune="29190", liste_enseignes=["ICI"]),
                 _place(commune="29190", liste_enseignes=["AUSSI ICI"]),
                 _place(commune="75101", liste_enseignes=["AILLEURS"]),
                 _place(commune="29190", liste_enseignes=["GARAGE"], activite_principale="45.20A")]}]},
             2: {"total_pages": 2, "results": [{"siren": "2", "nature_juridique": "1000", "nom_complet": "Prénom NOM", "matching_etablissements": [
                 _place(commune="29190")]}]}}
    notices = []
    monkeypatch.setattr(api_registre, "_get", lambda url, params: pages[params["page"]])
    monkeypatch.setattr(api_registre, "last_notice", lambda siren: notices.append(siren) or {})
    register = api_registre.read_register("29190")
    assert [line["nom"] for line in register["actifs"]] == ["ICI", "AUSSI ICI", None]
    assert sorted(set(notices)) == ["1", "2"]


def test_the_last_notice_gives_the_judgment(monkeypatch):
    row = {"familleavis_lib": "Procédures collectives", "dateparution": "2026-09-27", "jugement": '{"nature": "Liquidation judiciaire"}'}
    monkeypatch.setattr(api_registre, "_get", lambda url, params: {"results": [row]})
    assert api_registre.last_notice("1") == {"famille": "Procédures collectives", "date": "2026-09-27", "jugement": "Liquidation judiciaire"}


def test_no_notice_says_nothing(monkeypatch):
    monkeypatch.setattr(api_registre, "_get", lambda url, params: {"results": []})
    assert api_registre.last_notice("1") == {}


def test_a_closed_place_needs_no_notice(monkeypatch):
    called = []
    firm = {"siren": "1", "nature_juridique": "5710", "matching_etablissements": [
        _place("F", commune="29190", liste_enseignes=["LA MARINA"], date_fermeture="2026-03-12")]}
    monkeypatch.setattr(api_registre, "_get", lambda url, params: {"total_pages": 1, "results": [firm]})
    monkeypatch.setattr(api_registre, "last_notice", lambda siren: called.append(siren) or {})
    assert [line["nom"] for line in api_registre.read_register("29190")["enseignes_fermees"]] == ["LA MARINA"]
    assert called == []


def test_the_position_is_kept_for_the_zones():
    register = _register()
    add_establishment(register, _place(latitude="48.413256461", longitude="-4.478869501"), COMPANY, {}, "2021")
    assert register["actifs"][0]["position"] == [48.413256461, -4.478869501]


def test_a_hidden_position_leaves_the_line_without_position():
    register = _register()
    add_establishment(register, _place(latitude="[NON-DIFFUSIBLE]", longitude="[NON-DIFFUSIBLE]"), COMPANY, {}, "2021")
    assert register["actifs"] and "position" not in register["actifs"][0]
