import json
from types import SimpleNamespace

import pytest

from services.llm_service import LLMService, LLMUnavailable


def response(text=None, stop_reason="end_turn"):
    """Réponse minimale du SDK : une liste de blocs typés + un stop_reason."""
    content = [SimpleNamespace(type="text", text=text)] if text is not None else []
    return SimpleNamespace(content=content, stop_reason=stop_reason)


class FakeMessages:
    def __init__(self, reply):
        self.reply = reply
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return self.reply


SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}},
          "required": ["ok"], "additionalProperties": False}


def build(reply):
    service = LLMService(api_key="test")
    service._client = SimpleNamespace(messages=FakeMessages(reply))
    return service


def test_complete_json_returns_the_parsed_payload() -> None:
    service = build(response('{"ok": true}'))
    assert service.complete_json("sys", "user", SCHEMA) == {"ok": True}


def test_complete_json_constrains_the_output_format() -> None:
    service = build(response('{"ok": true}'))
    service.complete_json("sys", "user", SCHEMA)

    sent = service._client.messages.kwargs
    assert sent["output_config"]["format"] == {"type": "json_schema", "schema": SCHEMA}
    assert sent["model"] == "claude-opus-5"
    # Le prompt système est identique d'un spot à l'autre : il est mis en cache.
    assert sent["system"][0]["cache_control"] == {"type": "ephemeral"}
    # Ces paramètres sont rejetés par l'API sur ce modèle.
    assert "temperature" not in sent
    assert "top_p" not in sent


def test_complete_json_rejects_a_truncated_response() -> None:
    # Mieux vaut ne rien écrire en base qu'un enrichissement partiel.
    service = build(response('{"ok": tr', stop_reason="max_tokens"))
    with pytest.raises(LLMUnavailable, match="tronquée"):
        service.complete_json("sys", "user", SCHEMA)


def test_complete_json_rejects_a_refusal() -> None:
    service = build(response(None, stop_reason="refusal"))
    with pytest.raises(LLMUnavailable, match="refusée"):
        service.complete_json("sys", "user", SCHEMA)


def test_complete_json_rejects_a_response_without_text() -> None:
    service = build(response(None))
    with pytest.raises(LLMUnavailable, match="sans bloc texte"):
        service.complete_json("sys", "user", SCHEMA)


def test_complete_json_propagates_invalid_json() -> None:
    service = build(response("pas du json"))
    with pytest.raises(json.JSONDecodeError):
        service.complete_json("sys", "user", SCHEMA)


def test_missing_api_key_is_reported_clearly(monkeypatch) -> None:
    # Ce test porte sur la branche « clé absente », donc il suppose le SDK
    # installé ; sans lui c'est l'import qui échoue en premier, ce qui est aussi
    # le bon comportement mais n'est pas ce qu'on vérifie ici.
    pytest.importorskip("anthropic")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("utils.service_utils.ServiceUtil.load_env", lambda: None)
    with pytest.raises(LLMUnavailable, match="ANTHROPIC_API_KEY"):
        _ = LLMService().client


def test_fetch_batch_results_is_keyed_by_custom_id_and_skips_failures() -> None:
    # Les résultats d'un lot arrivent dans un ordre quelconque.
    results = [
        SimpleNamespace(custom_id="spot-2",
                        result=SimpleNamespace(type="succeeded", message=response('{"ok": true}'))),
        SimpleNamespace(custom_id="spot-1", result=SimpleNamespace(type="errored")),
        SimpleNamespace(custom_id="spot-3",
                        result=SimpleNamespace(type="succeeded", message=response("cassé"))),
    ]
    service = LLMService(api_key="test")
    service._client = SimpleNamespace(
        messages=SimpleNamespace(batches=SimpleNamespace(results=lambda batch_id: results))
    )

    assert service.fetch_batch_results("batch_1") == {"spot-2": {"ok": True}}


def test_batch_finished_reads_the_processing_status() -> None:
    service = LLMService(api_key="test")
    service._client = SimpleNamespace(
        messages=SimpleNamespace(batches=SimpleNamespace(
            retrieve=lambda batch_id: SimpleNamespace(processing_status="ended")
        ))
    )
    assert service.batch_finished("batch_1") is True
