import json
import subprocess
from types import SimpleNamespace

import pytest

from agents import llm_service
from agents.llm_service import (ClaudeCodeLLMService, LLMService, LLMUnavailable, mesure_objet,
                                object_of_label)
from services.llm_calls_service import QUERIES, cost_report

# La vraie fonction d'écriture, prise avant que conftest ne la remplace dans chaque test.
real_record_call = llm_service.record_call

SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}


# --- Moteur API ----------------------------------------------------------------

def api_service(stop_reason="end_turn", text='{"ok": true}'):
    usage = SimpleNamespace(input_tokens=120, output_tokens=30, cache_read_input_tokens=100,
                            cache_creation_input_tokens=0, server_tool_use=None)
    reply = SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], stop_reason=stop_reason, usage=usage)
    service = LLMService("modele-test", api_key="test", agent="harmonize_spots")
    service.client = SimpleNamespace(messages=SimpleNamespace(create=lambda **kwargs: reply))
    return service


def test_a_successful_api_call_is_recorded_with_its_object(llm_calls) -> None:
    with mesure_objet("spot", 42):
        assert api_service().complete_json("sys", "user", SCHEMA) == {"ok": True}

    [row] = llm_calls
    assert row["agent"] == "harmonize_spots"
    assert row["engine"] == "api"
    assert row["model"] == "modele-test"
    assert row["status"] == "reussi"
    assert (row["input_tokens"], row["output_tokens"], row["cache_read_tokens"]) == (120, 30, 100)
    assert (row["objet_type"], row["objet_id"]) == ("spot", 42)
    assert row["error"] is None


@pytest.mark.parametrize("stop_reason, status", [("refusal", "refus"), ("max_tokens", "coupe")])
def test_a_refused_or_truncated_api_call_is_recorded_then_raised(llm_calls, stop_reason, status) -> None:
    with pytest.raises(LLMUnavailable):
        api_service(stop_reason).complete_json("sys", "user", SCHEMA)
    assert llm_calls[0]["status"] == status


def test_the_object_is_forgotten_after_the_block(llm_calls) -> None:
    with mesure_objet("commune", 7):
        pass
    api_service().complete_json("sys", "user", SCHEMA)
    assert (llm_calls[0]["objet_type"], llm_calls[0]["objet_id"]) == (None, None)


def test_each_batch_answer_is_recorded_with_its_label_as_object(llm_calls) -> None:
    ok = SimpleNamespace(type="succeeded", message=SimpleNamespace(
        content=[SimpleNamespace(type="text", text='{"ok": true}')], stop_reason="end_turn", usage=None))
    items = [SimpleNamespace(custom_id="spot-12", result=ok),
             SimpleNamespace(custom_id="spot-13", result=SimpleNamespace(type="expired"))]
    service = LLMService("modele-test", api_key="test", agent="harmonize_spots")
    service.client = SimpleNamespace(messages=SimpleNamespace(batches=SimpleNamespace(results=lambda batch_id: items)))

    service.fetch_batch_results("lot-1")

    assert [(row["objet_id"], row["status"], row["engine"]) for row in llm_calls] == [
        (12, "reussi", "api-batch"), (13, "erreur", "api-batch")]


def test_object_of_label() -> None:
    assert object_of_label("spot-12") == ("spot", 12)
    assert object_of_label("lot") == (None, None)


# --- Moteur claude-code (CLI) ---------------------------------------------------

def cli_service(monkeypatch, stdout=None, raises=None):
    def fake_run(command, **kwargs):
        if raises:
            raise raises
        return SimpleNamespace(stdout=stdout, stderr="", returncode=0)

    monkeypatch.setattr(llm_service.shutil, "which", lambda name: "/usr/bin/claude")
    monkeypatch.setattr(llm_service.ServiceUtil, "load_env", staticmethod(lambda: None))
    monkeypatch.setattr(llm_service.subprocess, "run", fake_run)
    return ClaudeCodeLLMService("modele-test", effort="medium", agent="find_restaurants")


def result_line(**fields):
    return json.dumps({"type": "result", "is_error": False, "duration_ms": 5000, "total_cost_usd": 0.42,
                       "num_turns": 3, "structured_output": {"ok": True},
                       "usage": {"input_tokens": 900, "output_tokens": 200, "cache_read_input_tokens": 800,
                                 "cache_creation_input_tokens": 50, "server_tool_use": {"web_search_requests": 4}},
                       **fields})


def test_a_successful_cli_call_is_recorded_with_its_measures(monkeypatch, llm_calls) -> None:
    service = cli_service(monkeypatch, stdout=result_line())
    with mesure_objet("commune", 3):
        service.complete_json("sys", "user", SCHEMA)

    [row] = llm_calls
    assert (row["agent"], row["engine"], row["effort"], row["status"]) == ("find_restaurants", "claude-code", "medium", "reussi")
    assert (row["duration_ms"], row["cost_usd"], row["turns"]) == (5000, 0.42, 3)
    assert (row["input_tokens"], row["output_tokens"], row["cache_read_tokens"], row["cache_write_tokens"]) == (900, 200, 800, 50)
    assert row["web_searches"] == 4
    assert row["tools"] == "[]"
    assert (row["objet_type"], row["objet_id"]) == ("commune", 3)


def test_a_cli_timeout_is_recorded_as_delai(monkeypatch, llm_calls) -> None:
    service = cli_service(monkeypatch, raises=subprocess.TimeoutExpired("claude", 1))
    with pytest.raises(llm_service.LLMTimeout):
        service.complete_json("sys", "user", SCHEMA)
    assert llm_calls[0]["status"] == "delai"
    assert llm_calls[0]["duration_ms"] is not None


def test_an_unusable_cli_answer_keeps_its_cost(monkeypatch, llm_calls) -> None:
    # Un appel raté a consommé : son coût reste dans la mesure.
    service = cli_service(monkeypatch, stdout=result_line(is_error=True, result="quota"))
    with pytest.raises(LLMUnavailable):
        service.complete_json("sys", "user", SCHEMA)
    assert (llm_calls[0]["status"], llm_calls[0]["cost_usd"]) == ("erreur", 0.42)


# --- Écriture en base -----------------------------------------------------------

def test_a_broken_database_never_breaks_the_call(monkeypatch) -> None:
    def broken():
        raise RuntimeError("MySQL injoignable")

    monkeypatch.setattr("utils.db_utils.MySQLUtils.connect", staticmethod(broken))
    monkeypatch.setattr(llm_service, "record_call", real_record_call)
    assert api_service().complete_json("sys", "user", SCHEMA) == {"ok": True}


def test_record_call_inserts_every_column(monkeypatch) -> None:
    executed = []

    class Cursor:
        def execute(self, sql, values):
            executed.append((sql, values))

        def close(self):
            pass

    connection = SimpleNamespace(cursor=Cursor, commit=lambda: None, close=lambda: None)
    monkeypatch.setattr("utils.db_utils.MySQLUtils.connect", staticmethod(lambda: connection))
    real_record_call({"agent": "verify_spots", "status": "reussi"})

    [(sql, values)] = executed
    assert sql.startswith("INSERT INTO llm_calls")
    assert len(values) == len(llm_service.CALL_COLUMNS) == sql.count("%s")
    assert values[llm_service.CALL_COLUMNS.index("agent")] == "verify_spots"


# --- Bilans ---------------------------------------------------------------------

def test_cost_report_names_the_columns() -> None:
    class Cursor:
        description = [("agent",), ("appels",), ("cout_usd",)]

        def execute(self, sql):
            self.sql = sql

        def fetchall(self):
            return [("verify_spots", 10, 1.5)]

    cursor = Cursor()
    assert cost_report(cursor, "agent") == [{"agent": "verify_spots", "appels": 10, "cout_usd": 1.5}]
    assert "GROUP BY l.agent" in cursor.sql


def test_cost_report_covers_the_four_reports() -> None:
    assert set(QUERIES) == {"agent", "jour", "voyage", "commune"}
    with pytest.raises(ValueError):
        cost_report(None, "mois")
