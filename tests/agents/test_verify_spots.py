from datetime import date

from agents import verify_spots

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
        cursor, 374, {"statut": "plus_valable", "resume": " Rouvert en 2026. ", "sources": ["https://x"]}, "m",
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
    assert verify_spots.VERIFY_EFFORT != "low"


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
