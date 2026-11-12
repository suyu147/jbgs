import pytest

from app.config import settings


@pytest.fixture(autouse=True)
def disable_live_agent_for_api_tests(monkeypatch):
    """Keep the regression suite offline; the Coze adapter is mocked explicitly."""
    monkeypatch.setattr(settings, "agent_provider", "rules")
    monkeypatch.setattr(settings, "agent_pipeline_enabled", False)
    monkeypatch.setattr(settings, "agent_description_enabled", False)
    monkeypatch.setattr(settings, "deepseek_api_key", "")
