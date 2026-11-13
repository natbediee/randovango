import pytest

from etl.extract import api_registre
from etl.extract.api_registre import add_establishment, place_name


def _register():
    return {"actifs": [], "enseignes_fermees": [], "radies": []}


def _place(state="A", **fields):
    return {"etat_administratif": state, "adresse": "1 QUAI", "activite_principale": "56.10A", "date_creation": "2024-11-28", **fields}


COMPANY = {"nature_juridique": "5710", "nom_raison_sociale": "SARL AR DAGENTA"}
PERSON = {"nature_juridique": "1000", "nom_complet": "Prénom NOM"}


def test_the_sign_comes_first():
    """Le nom gardé est d'abord l'enseigne de l'établissement (NOUS)."""
    assert place_name({"liste_enseignes": ["NOUS"]}, COMPANY) == "NOUS"


def test_a_company_gives_its_name():
    """Sans enseigne, le nom gardé est celui de la société."""
    assert place_name({}, COMPANY) == "SARL AR DAGENTA"


def test_a_person_name_is_never_kept():
    """Le nom d'un entrepreneur individuel n'est jamais gardé : c'est celui d'une personne."""
    assert place_name({}, PERSON) is None


def test_a_strike_off_leaves_the_active_list():
    """Un établissement dont la société est radiée au BODACC sort des actifs, avec la date de sa radiation."""
    register = _register()
    add_establishment(register, _place(), COMPANY, {"famille": "Radiations", "date": "2023-02-24", "jugement": None}, "2021")
    assert register["actifs"] == [] and register["radies"][0]["radie_le"] == "2023-02-24"


def test_a_liquidation_stays_active_with_its_signal():
    """Une liquidation judiciaire laisse l'établissement dans les actifs, avec son annonce."""
    register = _register()
    notice = {"famille": "Procédures collectives", "date": "2026-09-27", "jugement": "Jugement d'ouverture de liquidation judiciaire"}
    add_establishment(register, _place(), COMPANY, notice, "2021")
    assert "liquidation" in register["actifs"][0]["derniere_annonce"]


def test_only_a_recent_closed_sign_is_kept():
    """Une enseigne fermée n'est gardée que si la fermeture est récente (La Marina, 2026)."""
    register = _register()
    add_establishment(register, _place("F", liste_enseignes=["LA MARINA"], date_fermeture="2026-03-12"), COMPANY, {}, "2021")
    add_establishment(register, _place("F", liste_enseignes=["TROP VIEUX"], date_fermeture="2006-01-01"), COMPANY, {}, "2021")
    assert [line["nom"] for line in register["enseignes_fermees"]] == ["LA MARINA"]


def test_an_unreadable_register_does_not_stop_the_search(monkeypatch):
    """Un registre qui ne répond pas rend None : la recherche continue sans lui."""
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
    """La dernière annonce du BODACC donne sa famille, sa date et la nature du jugement."""
    row = {"familleavis_lib": "Procédures collectives", "dateparution": "2026-09-27", "jugement": '{"nature": "Liquidation judiciaire"}'}
    monkeypatch.setattr(api_registre, "_get", lambda url, params: {"results": [row]})
    assert api_registre.last_notice("1") == {"famille": "Procédures collectives", "date": "2026-09-27", "jugement": "Liquidation judiciaire"}


def test_no_notice_says_nothing(monkeypatch):
    """Une société sans annonce au BODACC ne donne rien."""
    monkeypatch.setattr(api_registre, "_get", lambda url, params: {"results": []})
    assert api_registre.last_notice("1") == {}


def test_a_closed_place_needs_no_notice(monkeypatch):
    """Le BODACC n'est pas interrogé pour un établissement déjà fermé."""
    called = []
    firm = {"siren": "1", "nature_juridique": "5710", "matching_etablissements": [
        _place("F", commune="29190", liste_enseignes=["LA MARINA"], date_fermeture="2026-03-12")]}
    monkeypatch.setattr(api_registre, "_get", lambda url, params: {"total_pages": 1, "results": [firm]})
    monkeypatch.setattr(api_registre, "last_notice", lambda siren: called.append(siren) or {})
    assert [line["nom"] for line in api_registre.read_register("29190")["enseignes_fermees"]] == ["LA MARINA"]
    assert called == []


def test_the_position_is_kept_for_the_zones():
    """La position de l'établissement est gardée : elle découpe une grande ville en zones."""
    register = _register()
    add_establishment(register, _place(latitude="48.413256461", longitude="-4.478869501"), COMPANY, {}, "2021")
    assert register["actifs"][0]["position"] == [48.413256461, -4.478869501]


def test_a_hidden_position_leaves_the_line_without_position():
    """Un établissement non diffusible garde sa ligne, sans position (Brest)."""
    register = _register()
    add_establishment(register, _place(latitude="[NON-DIFFUSIBLE]", longitude="[NON-DIFFUSIBLE]"), COMPANY, {}, "2021")
    assert register["actifs"] and "position" not in register["actifs"][0]


def test_a_known_insee_code_and_the_asked_activities_read_the_register(monkeypatch):
    """La commune connue de cities (Trézien → 29177) évite une question à geo.api.gouv.fr ; les commerces lisent leurs codes."""
    monkeypatch.setattr(api_registre, "commune_code", lambda *args: pytest.fail("code INSEE déjà connu"))
    asked = []
    monkeypatch.setattr(api_registre, "read_register", lambda code, activities, near=None: asked.append((code, activities)) or _register())
    api_registre.load_register({"name": "Trézien", "insee": "29177", "latitude": 48.42, "longitude": -4.77}, ("47.24Z",))
    assert asked == [("29177", ("47.24Z",))]


def test_a_city_with_boroughs_is_read_around_its_zones(monkeypatch):
    """Le registre de Marseille est lu autour de chaque zone de recherche, à 1,5 km, et réuni : un établissement vu de deux zones voisines n'est gardé qu'une fois, et la ville entière (20 900 sociétés) n'est jamais lue."""
    asked = []

    def read(code, activities, near=None):
        asked.append((code, near))
        return {"actifs": [{"nom": "CHEZ FONFON"}, {"nom": f"TABLE {near[0]}"}], "enseignes_fermees": [], "radies": []}

    monkeypatch.setattr(api_registre, "read_register", read)
    monkeypatch.setattr(api_registre, "near_radius", lambda zone, activities, radius_km: radius_km)
    zones = [{"latitude": 43.24, "longitude": 5.37, "repere": "A"}, {"latitude": 43.29, "longitude": 5.36, "repere": "B"}]
    register = api_registre.load_register({"name": "Marseille", "insee": "13055", "latitude": 43.27, "longitude": 5.44}, zones=zones, radius_km=1.5)
    assert asked == [("13055", (43.24, 5.37, 1.5)), ("13055", (43.29, 5.36, 1.5))]
    assert [line["nom"] for line in register["actifs"]] == ["CHEZ FONFON", "TABLE 43.24", "TABLE 43.29"]


def test_around_a_point_the_borough_codes_are_those_of_the_commune(monkeypatch):
    """Autour d'un point, le registre garde les établissements des arrondissements de la commune (13208 pour Marseille) et laisse ceux d'une commune voisine."""
    asked = []
    firm = {"siren": "1", "nature_juridique": "5710", "matching_etablissements": [
        _place(commune="13208", liste_enseignes=["CHEZ FONFON"]), _place(commune="13119", liste_enseignes=["A CASSIS"])]}
    monkeypatch.setattr(api_registre, "_get", lambda url, params: asked.append((url, params)) or {"total_pages": 1, "results": [firm]})
    monkeypatch.setattr(api_registre, "last_notice", lambda siren: {})
    register = api_registre.read_register("13055", near=(43.24, 5.37, 1.5))
    assert [line["nom"] for line in register["actifs"]] == ["CHEZ FONFON"]
    url, params = asked[0]
    assert url == api_registre.NEAR_URL and (params["lat"], params["long"], params["radius"]) == (43.24, 5.37, 1.5) and "code_commune" not in params


LIDL = {"siren": "343262622", "nature_juridique": "5202", "nom_raison_sociale": "LIDL", "nombre_etablissements": 2810}
OLD_LIDL = _place("F", siret="34326262200001", commune="29260", activite_principale="47.11D", liste_enseignes=["LIDL"],
                  date_fermeture="2024-01-20")
NEW_LIDL = _place(siret="34326262200002", commune="29260", activite_principale="47.11D", liste_enseignes=["LIDL"],
                  date_creation="2024-09-25")


def test_a_firm_with_several_places_is_asked_again_by_its_name(monkeypatch):
    """Une société à plusieurs établissements est redemandée à son nom : le registre voit le nouveau Lidl de Saint-Renan, ouvert en septembre 2024, à côté de l'ancien fermé, que l'API seule rendait (passage des supermarchés du 13 novembre 2026)."""
    asked = []

    def get(url, params):
        asked.append(params)
        places = [OLD_LIDL, NEW_LIDL] if "q" in params else [OLD_LIDL]
        return {"total_pages": 1, "results": [{**LIDL, "matching_etablissements": places}]}

    monkeypatch.setattr(api_registre, "_get", get)
    monkeypatch.setattr(api_registre, "last_notice", lambda siren: {})
    register = api_registre.read_register("29260", ("47.11D", "47.11F"))
    assert [(line["nom"], line["actif_depuis"]) for line in register["actifs"]] == [("LIDL", "2024-09-25")]
    assert [line["ferme_le"] for line in register["enseignes_fermees"]] == ["2024-01-20"]
    assert (asked[1]["q"], asked[1]["code_commune"]) == ("LIDL", "29260")


def test_a_firm_with_a_single_place_is_not_asked_again(monkeypatch):
    """Une société à un seul établissement n'est pas redemandée : la première réponse l'a déjà tout entière."""
    asked = []
    firm = {"siren": "1", "nature_juridique": "5710", "nom_raison_sociale": "FINIS TERRA", "nombre_etablissements": 1,
            "matching_etablissements": [_place(commune="29260", activite_principale="47.11D")]}
    monkeypatch.setattr(api_registre, "_get", lambda url, params: asked.append(params) or {"total_pages": 1, "results": [firm]})
    monkeypatch.setattr(api_registre, "last_notice", lambda siren: {})
    assert len(api_registre.read_register("29260", ("47.11D",))["actifs"]) == 1 and len(asked) == 1


def test_around_a_point_a_firm_asked_by_name_keeps_only_the_places_in_the_radius(monkeypatch):
    """Autour d'un point, l'API refuse un nom : la société est redemandée dans tous les arrondissements de Marseille, et seuls ses établissements du rayon sont gardés."""
    asked = []
    near_place = _place(siret="2", commune="13201", liste_enseignes=["LIDL"], latitude="43.2990", longitude="5.3790")
    far_place = _place(siret="3", commune="13204", liste_enseignes=["LIDL"], latitude="43.3080", longitude="5.4050")

    def get(url, params):
        asked.append((url, params))
        places = [near_place, far_place] if "q" in params else []
        return {"total_pages": 1, "results": [{**LIDL, "matching_etablissements": places}]}

    monkeypatch.setattr(api_registre, "_get", get)
    monkeypatch.setattr(api_registre, "last_notice", lambda siren: {})
    register = api_registre.read_register("13055", near=(43.2985, 5.3785, 0.5))
    assert len(register["actifs"]) == 1
    url, params = asked[1]
    assert url == api_registre.SIRENE_URL and params["code_commune"] == ",".join(api_registre.BOROUGHS["13055"])


def test_paris_and_lyon_have_their_boroughs_too():
    """Paris (20 arrondissements) et Lyon (9) ont le même défaut que Marseille : leurs codes d'arrondissement sont connus."""
    assert api_registre.BOROUGHS["75056"][0] == "75101" and len(api_registre.BOROUGHS["75056"]) == 20
    assert api_registre.BOROUGHS["69123"] == tuple(f"6938{number}" for number in range(1, 10))


# --- Un appel qui échoue est repris ---

class _Response:
    def __init__(self, status):
        self.status_code = status

    def json(self):
        return {"total_pages": 1, "results": []}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise api_registre.requests.HTTPError(str(self.status_code), response=self)


def _calls(monkeypatch, answers):
    """Le registre répond tour à tour par ces réponses (un code HTTP, ou une erreur à lever). Rend les attentes faites."""
    waits, left = [], list(answers)

    def get(url, params, timeout, headers):
        answer = left.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return _Response(answer)

    monkeypatch.setattr(api_registre.requests, "get", get)
    monkeypatch.setattr(api_registre.time, "sleep", waits.append)
    return waits


def test_a_call_that_fails_is_tried_again(monkeypatch):
    """Un appel sans réponse, puis refusé (503), est repris après une attente plus longue à chaque fois : le registre de Marseille, ce sont des milliers d'appels."""
    waits = _calls(monkeypatch, [api_registre.requests.Timeout("lent"), 503, 200])
    assert api_registre._get("https://registre", {}) == {"total_pages": 1, "results": []}
    assert waits == [api_registre.PAUSE_SECONDS, 2, 10]


def test_a_register_that_never_answers_gives_up_after_the_last_wait(monkeypatch):
    """Un registre qui ne répond à aucune reprise finit par lever l'erreur : la lecture s'arrête, elle ne tourne pas sans fin."""
    waits = _calls(monkeypatch, [503, 503, 503, 503])
    with pytest.raises(api_registre.requests.HTTPError):
        api_registre._get("https://registre", {})
    assert waits == [api_registre.PAUSE_SECONDS, *api_registre.RETRY_PAUSES]


def test_a_wrong_request_is_not_tried_again(monkeypatch):
    """Une demande refusée pour de bon (404) n'est pas reprise : attendre n'y changerait rien."""
    waits = _calls(monkeypatch, [404])
    with pytest.raises(api_registre.requests.HTTPError):
        api_registre._get("https://registre", {})
    assert waits == [api_registre.PAUSE_SECONDS]


def test_a_very_dense_zone_is_read_closer_to_its_spot(monkeypatch):
    """Autour du Vieux-Port de Marseille (7 100 sociétés à 1,5 km), le registre est lu à 375 m, où il n'en reste que 480 : l'agent n'en lit de toute façon que les lignes les plus proches du spot. Une zone de la périphérie garde ses 1,5 km."""
    counts = {1.5: 7114, 0.75: 2974, 0.375: 480}
    monkeypatch.setattr(api_registre, "_get", lambda url, params: {"total_results": counts[params["radius"]]})
    centre = {"latitude": 43.2962, "longitude": 5.37, "repere": "Vieux-Port"}
    assert api_registre.near_radius(centre, ("56.10A",), 1.5) == 0.375
    monkeypatch.setattr(api_registre, "_get", lambda url, params: {"total_results": 450})
    assert api_registre.near_radius(centre, ("56.10A",), 1.5) == 1.5


def test_the_reading_radius_never_goes_under_its_floor(monkeypatch):
    """Même dans une zone où le registre déborde toujours, le rayon de lecture ne descend pas sous son plancher : il faut encore de quoi lire les lignes proches du spot."""
    monkeypatch.setattr(api_registre, "_get", lambda url, params: {"total_results": 99999})
    assert api_registre.MIN_RADIUS_KM / 2 < api_registre.near_radius({"latitude": 43.3, "longitude": 5.37}, ("56.10A",), 1.5) <= api_registre.MIN_RADIUS_KM
