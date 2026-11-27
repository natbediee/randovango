import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from agents.llm_service import LLMLimitReached, LLMService, LLMUnavailable


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
    service = LLMService("modele-test", api_key="test")
    service.client = SimpleNamespace(messages=FakeMessages(reply))
    return service


def test_complete_json_returns_the_parsed_payload() -> None:
    service = build(response('{"ok": true}'))
    assert service.complete_json("sys", "user", SCHEMA) == {"ok": True}


def test_complete_json_constrains_the_output_format() -> None:
    service = build(response('{"ok": true}'))
    service.complete_json("sys", "user", SCHEMA)

    sent = service.client.messages.kwargs
    assert sent["output_config"]["format"] == {"type": "json_schema", "schema": SCHEMA}
    assert sent["model"] == "modele-test"
    # Le prompt système est identique d'un spot à l'autre : il est mis en cache.
    assert sent["system"][0]["cache_control"] == {"type": "ephemeral"}
    # Ces paramètres sont rejetés par l'API sur ce modèle.
    assert "temperature" not in sent
    assert "top_p" not in sent


def test_complete_json_rejects_a_truncated_response() -> None:
    # Mieux vaut ne rien écrire en base qu'une harmonisation partielle.
    service = build(response('{"ok": tr', stop_reason="max_tokens"))
    with pytest.raises(LLMUnavailable, match="coupée"):
        service.complete_json("sys", "user", SCHEMA)


def test_complete_json_rejects_a_refusal() -> None:
    service = build(response(None, stop_reason="refusal"))
    with pytest.raises(LLMUnavailable, match="refusé"):
        service.complete_json("sys", "user", SCHEMA)


def test_complete_json_rejects_a_response_without_text() -> None:
    service = build(response(None))
    with pytest.raises(LLMUnavailable, match="sans texte"):
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
        LLMService("modele-test")._get_client()


def test_fetch_batch_results_is_keyed_by_custom_id_and_skips_failures() -> None:
    # Les résultats d'un lot arrivent dans un ordre quelconque.
    results = [
        SimpleNamespace(custom_id="spot-2",
                        result=SimpleNamespace(type="succeeded", message=response('{"ok": true}'))),
        SimpleNamespace(custom_id="spot-1", result=SimpleNamespace(type="errored")),
        SimpleNamespace(custom_id="spot-3",
                        result=SimpleNamespace(type="succeeded", message=response("cassé"))),
    ]
    service = LLMService("modele-test", api_key="test")
    service.client = SimpleNamespace(
        messages=SimpleNamespace(batches=SimpleNamespace(results=lambda batch_id: results))
    )

    assert service.fetch_batch_results("batch_1") == {"spot-2": {"ok": True}}


def test_batch_finished_reads_the_processing_status() -> None:
    service = LLMService("modele-test", api_key="test")
    service.client = SimpleNamespace(
        messages=SimpleNamespace(batches=SimpleNamespace(
            retrieve=lambda batch_id: SimpleNamespace(processing_status="ended")
        ))
    )
    assert service.batch_finished("batch_1") is True


def test_a_long_question_goes_through_standard_input(monkeypatch) -> None:
    # Le registre de Brest dépasse 128 Ko : en argument, Linux refusait la commande.
    from agents import llm_service
    calls = {}

    def fake_run(command, **kwargs):
        calls["command"], calls["input"] = command, kwargs.get("input")
        result = {"type": "result", "is_error": False, "structured_output": {"ok": True}}
        return SimpleNamespace(stdout=json.dumps(result), stderr="", returncode=0)

    monkeypatch.setattr(llm_service.shutil, "which", lambda name: "/usr/bin/claude")
    monkeypatch.setattr(llm_service.ServiceUtil, "load_env", staticmethod(lambda: None))
    monkeypatch.setattr(llm_service.subprocess, "run", fake_run)
    question = "x" * 300_000
    assert llm_service.ClaudeCodeLLMService("modele-test").complete_json("sys", question, SCHEMA) == {"ok": True}
    assert calls["input"] == question
    assert all(len(part) < 128_000 for part in calls["command"])


# --- Les limites du fournisseur, traduites en LLMLimitReached (issue #332) ---

# Le 27 novembre 2026 à 6 h 11, heure de Paris (UTC+1) : le quota des agents coupé ce matin-là.
MORNING = datetime(2026, 11, 27, 6, 11, tzinfo=timezone(timedelta(hours=1)))


def local(moment: datetime) -> datetime:
    """Une heure avec fuseau, ramenée à l'heure locale du serveur sans fuseau, comme la rend llm_service."""
    return moment.astimezone().replace(tzinfo=None)


def test_the_reset_hour_in_utc_is_read_in_local_time() -> None:
    """« resets 1:40pm (UTC) », lu à 6 h 11 à Paris : les agents reviennent à 13 h 40 UTC le même jour."""
    from agents import llm_service
    reset = llm_service.reset_time("You've hit your session limit · resets 1:40pm (UTC)", MORNING)
    assert reset == local(datetime(2026, 11, 27, 13, 40, tzinfo=timezone.utc))


def test_a_reset_hour_already_past_is_tomorrow() -> None:
    """« resets 2am (Europe/Paris) », lu à 6 h 11 : l'heure est passée, c'est celle du lendemain."""
    from agents import llm_service
    reset = llm_service.reset_time("usage limit reached · resets 2am (Europe/Paris)", MORNING)
    assert reset == local(datetime(2026, 11, 28, 1, 0, tzinfo=timezone.utc))


def test_the_quota_becomes_a_limit_until_its_reset_hour() -> None:
    """Le quota de l'abonnement devient une limite neutre : jusqu'à l'heure dite, deux minutes de plus, sans nommer le fournisseur."""
    from agents import llm_service
    limit = llm_service.limit_reached("You've hit your session limit · resets 1:40pm (UTC)", MORNING)
    assert limit.until == local(datetime(2026, 11, 27, 13, 42, tzinfo=timezone.utc))
    assert limit.reason == "quota des agents atteint" and isinstance(limit, LLMUnavailable)


def test_a_quota_without_a_readable_hour_waits_half_an_hour() -> None:
    """Un quota sans heure lisible fait réessayer une demi-heure plus tard."""
    from agents import llm_service
    now = datetime(2026, 11, 27, 6, 11)
    assert llm_service.limit_reached("You've hit your usage limit", now).until == now + timedelta(minutes=30)


def test_too_many_calls_waits_five_minutes() -> None:
    """Trop d'appels à la minute (erreur 429) : une limite de cinq minutes."""
    from agents import llm_service
    now = datetime(2026, 11, 27, 6, 11)
    limit = llm_service.limit_reached("Error code: 429 - rate_limit_error", now)
    assert limit.until == now + timedelta(minutes=5) and limit.reason == "trop d'appels aux agents en même temps"


@pytest.mark.parametrize("message", ["Error code: 400 - Your credit balance is too low", "division by zero"])
def test_an_empty_credit_or_a_real_failure_is_not_a_limit(message) -> None:
    """Le crédit de l'API épuisé ne revient pas seul, une vraie panne non plus : ce ne sont pas des limites passagères."""
    from agents import llm_service
    assert llm_service.limit_reached(message, datetime(2026, 11, 27, 6, 11)) is None


def test_the_subscription_quota_raises_a_limit(monkeypatch) -> None:
    """Le programme claude répond « session limit » : l'appel lève LLMLimitReached, que la file sait attendre (27 novembre 2026)."""
    from agents import llm_service

    def fake_run(command, **kwargs):
        result = {"type": "result", "is_error": True, "result": "You've hit your session limit · resets 1:40pm (UTC)"}
        return SimpleNamespace(stdout=json.dumps(result), stderr="", returncode=1)

    monkeypatch.setattr(llm_service.shutil, "which", lambda name: "/usr/bin/claude")
    monkeypatch.setattr(llm_service.ServiceUtil, "load_env", staticmethod(lambda: None))
    monkeypatch.setattr(llm_service.subprocess, "run", fake_run)
    with pytest.raises(LLMLimitReached):
        llm_service.ClaudeCodeLLMService("modele-test").complete_json("sys", "question", SCHEMA)


def test_too_many_api_calls_raise_a_limit() -> None:
    """L'API répond 429 : l'appel lève LLMLimitReached au lieu de l'erreur brute du module anthropic."""
    class Busy:
        def create(self, **kwargs):
            raise RuntimeError("Error code: 429 - {'type': 'rate_limit_error'}")
    service = LLMService("modele-test", api_key="test")
    service.client = SimpleNamespace(messages=Busy())
    with pytest.raises(LLMLimitReached):
        service.complete_json("sys", "user", SCHEMA)
