import pytest

from agents import llm_config
from agents.llm_service import ClaudeCodeLLMService, LLMService


@pytest.fixture
def settings(monkeypatch):
    monkeypatch.setattr(llm_config.ServiceUtil, "load_env", staticmethod(lambda: None))
    monkeypatch.setenv("LLM_ENGINE", "claude-code")
    monkeypatch.setenv("LLM_MODEL_QUALITE", "opus-x")
    monkeypatch.setenv("LLM_MODEL_RAPIDE", "sonnet-x")


def test_an_agent_gets_the_model_of_its_level(settings, monkeypatch) -> None:
    assert llm_config.model_of("discover_places") == "opus-x"
    monkeypatch.setitem(llm_config.AGENTS, "discover_places", llm_config.AgentConfig(llm_config.RAPIDE, "low", 60))
    assert llm_config.model_of("discover_places") == "sonnet-x"


def test_the_service_carries_the_settings_of_the_agent(settings) -> None:
    service = llm_config.make_llm_service("verify_spots")
    assert isinstance(service, ClaudeCodeLLMService)
    assert (service.model, service.effort, service.timeout) == ("opus-x", "high", 400)
    assert service.tools == llm_config.WEB_TOOLS
    assert llm_config.make_llm_service("choose_pepites").tools == []


def test_a_missing_setting_fails_right_away(settings, monkeypatch) -> None:
    monkeypatch.delenv("LLM_MODEL_QUALITE")
    with pytest.raises(llm_config.LLMConfigError, match="LLM_MODEL_QUALITE"):
        llm_config.make_llm_service("choose_pepites")


def test_an_unknown_engine_is_refused(settings, monkeypatch) -> None:
    monkeypatch.setenv("LLM_ENGINE", "autre")
    with pytest.raises(llm_config.LLMConfigError, match="LLM_ENGINE"):
        llm_config.engine()


def test_the_api_engine_cannot_serve_a_web_agent_yet(settings, monkeypatch) -> None:
    monkeypatch.setenv("LLM_ENGINE", "api")
    assert isinstance(llm_config.make_llm_service("harmonize_spots"), LLMService)
    with pytest.raises(llm_config.LLMConfigError, match="discover_places"):
        llm_config.make_llm_service("discover_places")


def test_an_option_forces_the_engine_and_the_model(settings) -> None:
    service = llm_config.make_llm_service("harmonize_spots", chosen_engine="api", model="autre")
    assert isinstance(service, LLMService) and service.model == "autre"


def test_every_agent_has_a_known_level() -> None:
    assert all(config.niveau in llm_config.MODEL_VARS for config in llm_config.AGENTS.values())
