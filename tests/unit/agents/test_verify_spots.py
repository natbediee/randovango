from datetime import date

from agents import llm_config, verify_spots

SPOT = {
    "id": 374, "name_label": "Parking · Rue des Cormorans", "city_label": "Brest", "postal_code": "29200",
    "latitude": 48.39, "longitude": -4.43, "url": "https://park4night.com/fr/place/1",
    "details_scraped_at": date(2026, 10, 8), "type": "CAMPING",
    "opening_period": "Temporarily closed for works",
    "recent_reviews": [{"review_date": date(2026, 9, 14), "text": "Toujours fermé."}],
    "description_ia": "Parking éclairé.\n\nÀ savoir : parking fermé depuis le 25 juin 2024.",
}


class FakeCursor:
    description = [("id",)]

    def __init__(self):
        self.calls = []

    def execute(self, query, params=None):
        self.calls.append((" ".join(query.split()), params))

    def fetchall(self):
        return []


def test_message_identifies_the_place_and_isolates_the_information_to_check() -> None:
    message = verify_spots.build_user_message(SPOT)
    assert "Brest (29200)" in message and "48.39, -4.43" in message
    # v3 : état actuel de la fiche et commentaires récents.
    assert "ÉTAT ACTUEL DE LA FICHE (relue le 08/10/2026)" in message
    assert "- ouverture : Temporarily closed for works" in message
    assert '- 14/09/2026 : "Toujours fermé."' in message
    # Seul le paragraphe « À savoir » est à vérifier, pas toute la description.
    assert "INFORMATION À VÉRIFIER : parking fermé depuis le 25 juin 2024." in message
    assert "Parking éclairé" not in message
    # L'agent doit connaître la date du jour pour juger une période terminée.
    assert f"DATE DU JOUR : {date.today().strftime('%d/%m/%Y')}" in message


def test_only_flagged_spots_not_verified_since_harmonization() -> None:
    cursor = FakeCursor()
    verify_spots.fetch_spots_to_verify(cursor, limit=5)
    query, params = cursor.calls[0]
    assert "s.a_verifier = 1" in query
    assert "v.verified_at >= s.harmonized_at" in query
    # Une ancienne version du prompt de vérification fait tout revérifier.
    assert "v.prompt_version >= %s" in query
    assert params[-2:] == (verify_spots.VERIFY_PROMPT_VERSION, 5)
    assert "PARKING JOUR UNIQUEMENT" in params  # types masqués exclus


def test_a_verification_is_a_new_row_and_never_touches_the_spot() -> None:
    cursor = FakeCursor()
    verify_spots.write_verification(
        cursor, 374, {"statut": "plus_valable", "resume": " Rouvert en 2026. ", "sources": ["https://x"], "a_savoir": [],
                      "utilisable": "oui", "utilisable_a_partir": None, "raison": ""}, "m",
    )
    query, params = cursor.calls[0]
    assert query.startswith("INSERT INTO spot_verifications")
    assert "UPDATE spots" not in query
    assert params[1:3] == ("plus_valable", "Rouvert en 2026.")


def test_prompt_prefers_uncertain_and_forbids_own_knowledge() -> None:
    prompt = " ".join(verify_spots.SYSTEM_PROMPT.split())  # sans retours à la ligne
    assert "C'est la réponse attendue en cas de doute" in prompt
    assert "N'utilise pas tes connaissances" in prompt
    assert verify_spots.VERIFY_SCHEMA["properties"]["statut"]["enum"] == [
        "toujours_valable", "plus_valable", "incertain"]


def test_a_finished_period_is_no_longer_valid() -> None:
    prompt = verify_spots.SYSTEM_PROMPT
    assert "période déjà terminée" in prompt
    assert llm_config.AGENTS["verify_spots"].effort != "low"


def test_v3_rules_on_reopening_and_partial_end() -> None:
    prompt = " ".join(verify_spots.SYSTEM_PROMPT.split())
    assert "la fin d'une période ne prouve pas une réouverture" in prompt
    assert "TOUTES les situations signalées ont pris fin" in prompt


def test_summary_has_no_price() -> None:
    # Un tarif se périme : ni l'harmonisation ni la vérification ne l'écrivent.
    assert "pas de tarif chiffré" in " ".join(verify_spots.SYSTEM_PROMPT.split())


def test_commune_testimonies_are_a_tool_not_pushed_in_the_message() -> None:
    # Pas d'informations inutiles d'office : l'agent appelle l'outil s'il en a besoin.
    message = verify_spots.build_user_message(SPOT)
    assert "TÉMOIGNAGES DES AUTRES SPOTS" not in message
    assert "IDENTIFIANT DU SPOT : 374" in message  # nécessaire pour appeler l'outil
    assert verify_spots.MCP_TOOLS == ["mcp__randovango__temoignages_commune"]
    prompt = " ".join(verify_spots.SYSTEM_PROMPT.split())
    assert "et seulement dans ce cas, appelle l'outil temoignages_commune" in prompt


def test_only_the_comments_of_the_last_twelve_months_are_read() -> None:
    today = date(2026, 11, 2)
    reviews = [{"review_date": date(2026, 1, 8), "text": "Réparé"}, {"review_date": date(2025, 7, 30), "text": "Panne"},
               {"review_date": None, "text": "Sans date"}, {"review_date": date(2026, 9, 26), "text": "Récent"}]
    assert [r["text"] for r in verify_spots.recent_reviews(reviews, today)] == ["Récent", "Réparé"]


def test_a_seasonal_rule_keeps_a_valid_period_and_a_bad_one_is_dropped() -> None:
    items = [{"texte": " Chiens interdits sur la plage. ", "debut": None, "fin": "09-30"},
             {"texte": "Séjour limité.", "debut": "été", "fin": "13-01"}, {"texte": " ", "debut": None, "fin": None}]
    assert verify_spots.clean_a_savoir(items) == [
        {"texte": "Chiens interdits sur la plage.", "debut": None, "fin": "09-30"},
        {"texte": "Séjour limité.", "debut": None, "fin": None}]


def test_an_unreadable_reopening_date_keeps_the_place_closed() -> None:
    assert verify_spots.clean_reopening("2027-05-01") == "2027-05-01"
    assert verify_spots.clean_reopening("mai 2027") is None
    assert verify_spots.clean_reopening(None) is None


def test_a_height_limit_does_not_make_a_place_unusable() -> None:
    assert "limite de hauteur" in verify_spots.SYSTEM_PROMPT
    assert "L'absence de nouvelles n'est pas une preuve" in verify_spots.SYSTEM_PROMPT


def test_a_doubt_removes_the_verified_badge_and_nothing_else() -> None:
    assert verify_spots.is_doubtful({"statut": "incertain", "utilisable": "oui"})
    assert verify_spots.is_doubtful({"statut": "toujours_valable", "utilisable": "non"})
    assert not verify_spots.is_doubtful({"statut": "toujours_valable", "utilisable": "oui"})
    cursor = FakeCursor()
    verify_spots.mark_doubt(cursor, 374)
    query, params = cursor.calls[0]
    assert query == "UPDATE spots SET verifie = 0 WHERE id = %s" and params == (374,)


def test_three_failures_in_a_row_stop_the_pass(monkeypatch) -> None:
    calls = []

    class Unavailable:
        model = "modele-test"

        def complete_json(self, *args):
            calls.append(args)
            raise verify_spots.LLMUnavailable("quota")

    class Driver:
        def quit(self):
            pass

    class Cursor(FakeCursor):
        def close(self):
            pass

    class Connection:
        def cursor(self):
            return Cursor()

        def commit(self):
            pass

    spots = [dict(SPOT, id=number) for number in range(5)]
    monkeypatch.setattr(verify_spots, "make_llm_service", lambda *args, **kwargs: Unavailable())
    monkeypatch.setattr(verify_spots.ServiceUtil, "load_env", lambda: None)
    monkeypatch.setattr(verify_spots.MySQLUtils, "connect", lambda: Connection())
    monkeypatch.setattr(verify_spots.MySQLUtils, "disconnect", lambda connection: None)
    monkeypatch.setattr(verify_spots, "fetch_spots_to_verify", lambda *args, **kwargs: spots)
    monkeypatch.setattr(verify_spots, "read_recent_reviews", lambda *args, **kwargs: None)
    monkeypatch.setattr("etl.extract.scraper_p4n.create_driver", lambda: Driver())

    verify_spots.run()

    assert len(calls) == verify_spots.MAX_FAILURES_IN_A_ROW


def test_only_new_leaves_the_spots_already_verified_alone() -> None:
    cursor = FakeCursor()
    verify_spots.fetch_spots_to_verify(cursor, only_new=True)
    query, params = cursor.calls[0]
    assert "v.prompt_version" not in query
    assert "v.verified_at" not in query
    assert verify_spots.VERIFY_PROMPT_VERSION not in params
