import json

import pytest

from etl.enrich import enrich_spots


SPOT = {
    "id": 1,
    "name": "(29200) Brest - 172 Rue de Quimper",
    "description": "Nous avons dormi 1 nuit, assez calme. Vue sur la rade.",
    "type": "PARKING JOUR ET NUIT",
    "postal_code": "29200",
    "city_label": "Brest",
    "place_label": "172 Rue de Quimper",
    "services": ["Eau potable", "Toilettes"],
}

PAYLOAD = {
    "display_name": "Parking de la rade",
    "summary": "Stationnement calme avec vue sur la rade.",
    "tags": ["calme", "vue_mer"],
    "noise_level": "calme",
    "access_difficulty": "inconnu",
    "services_inferred": ["Eau potable"],
    "stale_info": False,
    "confidence": "moyenne",
}


class FakeLLM:
    """Double du service : enregistre les appels, renvoie une charge utile fixée."""

    def __init__(self, payload=None):
        self.payload = payload or PAYLOAD
        self.calls = []

    def complete_json(self, system, user, schema):
        self.calls.append({"system": system, "user": user, "schema": schema})
        return self.payload


def test_source_hash_stable_across_service_order() -> None:
    # L'ordre des services vient d'un SELECT non trié : il ne doit pas faire
    # croire que la source a changé.
    reordered = {**SPOT, "services": ["Toilettes", "Eau potable"]}
    assert enrich_spots.source_hash(SPOT) == enrich_spots.source_hash(reordered)


def test_source_hash_changes_when_description_changes() -> None:
    modified = {**SPOT, "description": "Parking désormais payant."}
    assert enrich_spots.source_hash(SPOT) != enrich_spots.source_hash(modified)


def test_source_hash_changes_when_a_service_is_added() -> None:
    modified = {**SPOT, "services": [*SPOT["services"], "Laverie"]}
    assert enrich_spots.source_hash(SPOT) != enrich_spots.source_hash(modified)


def test_build_user_prompt_contains_source_text_and_context() -> None:
    prompt = enrich_spots.build_user_prompt(SPOT)
    assert SPOT["description"] in prompt
    assert "Brest" in prompt
    assert "Eau potable, Toilettes" in prompt


def test_build_user_prompt_marks_missing_fields() -> None:
    bare = {"id": 2, "type": None, "description": None, "services": []}
    prompt = enrich_spots.build_user_prompt(bare)
    assert "Commune : inconnue" in prompt
    assert "Services déjà connus : aucun" in prompt
    assert "(vide)" in prompt


def test_enrich_one_passes_schema_and_returns_payload() -> None:
    service = FakeLLM()
    assert enrich_spots.enrich_one(service, SPOT) == PAYLOAD
    assert service.calls[0]["schema"] is enrich_spots.SPOT_SCHEMA
    assert "n'invente rien" in service.calls[0]["system"]


def test_normalize_truncates_summary_on_a_word_boundary() -> None:
    long_summary = "Stationnement " * 30
    fields = enrich_spots.normalize({**PAYLOAD, "summary": long_summary})
    assert len(fields["description_ia"]) <= 200
    assert fields["description_ia"].endswith("…")


def test_normalize_turns_empty_display_name_into_null() -> None:
    # Le front doit pouvoir retomber franchement sur le nom d'origine.
    fields = enrich_spots.normalize({**PAYLOAD, "display_name": "   "})
    assert fields["display_name"] is None


def test_normalize_serializes_lists_as_json() -> None:
    fields = enrich_spots.normalize(PAYLOAD)
    assert json.loads(fields["tags"]) == ["calme", "vue_mer"]
    assert json.loads(fields["services_inferred"]) == ["Eau potable"]


def test_normalize_defaults_a_missing_payload_to_the_cautious_values() -> None:
    fields = enrich_spots.normalize({})
    assert fields["confidence"] == "faible"
    assert fields["noise_level"] == "inconnu"
    assert fields["stale_info"] == 0


def test_schema_vocabularies_are_closed() -> None:
    # Les énumérations sont ce qui empêche le modèle d'inventer un tag ou un service.
    properties = enrich_spots.SPOT_SCHEMA["properties"]
    assert properties["tags"]["items"]["enum"] == enrich_spots.TAGS
    assert "Eau potable" in properties["services_inferred"]["items"]["enum"]
    assert enrich_spots.SPOT_SCHEMA["additionalProperties"] is False


def test_description_column_is_never_written() -> None:
    # Garde-fou principal : la source Park4Night doit rester rejouable.
    executed = []

    class Cursor:
        def execute(self, query, params=None):
            executed.append(query)

    enrich_spots.write_enrichment(Cursor(), 1, "abc", PAYLOAD)
    statement = executed[0]
    assert "description_ia" in statement
    assert "description =" not in statement.replace("description_ia =", "")


@pytest.mark.parametrize("column", ["display_name", "description_ia", "confidence", "source_hash"])
def test_enrichment_columns_are_declared(column) -> None:
    assert column in enrich_spots.ENRICHMENT_COLUMNS
