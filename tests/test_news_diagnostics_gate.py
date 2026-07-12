import builtins
import inspect

import pytest

from components import news_diagnostics
from components.news_diagnostics import render_news_schema_diagnostics_if_enabled
from dashboard_support.dev_mode import is_dev_diagnostics_enabled


@pytest.fixture(autouse=True)
def forbid_external_access(monkeypatch):
    import openai
    import requests
    import yfinance

    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: pytest.fail("requests must not run"))
    monkeypatch.setattr(yfinance, "Ticker", lambda *args, **kwargs: pytest.fail("yfinance must not run"))
    monkeypatch.setattr(openai, "OpenAI", lambda *args, **kwargs: pytest.fail("OpenAI must not run"))
    monkeypatch.setattr(builtins, "open", lambda *args, **kwargs: pytest.fail("file I/O must not run"))


def test_dev_diagnostics_is_disabled_by_default():
    assert is_dev_diagnostics_enabled() is False


@pytest.mark.parametrize(
    ("config", "expected"),
    [
        ({"enable_news_diagnostics": True}, True),
        ({"enable_news_diagnostics": False}, False),
    ],
)
def test_explicit_config_controls_gate(config, expected):
    assert is_dev_diagnostics_enabled(config=config) is expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [("1", True), ("true", True), (" TRUE ", True), ("0", False)],
)
def test_caller_supplied_environment_controls_gate(value, expected):
    assert is_dev_diagnostics_enabled(env={"ENABLE_NEWS_DIAGNOSTICS": value}) is expected


def test_missing_caller_supplied_environment_value_is_disabled():
    assert is_dev_diagnostics_enabled(env={}) is False


def test_explicit_config_is_authoritative_over_environment():
    assert is_dev_diagnostics_enabled(
        config={"enable_news_diagnostics": False},
        env={"ENABLE_NEWS_DIAGNOSTICS": "true"},
    ) is False


def test_gate_does_not_read_process_environment_or_streamlit_secrets():
    source = inspect.getsource(inspect.getmodule(is_dev_diagnostics_enabled))

    assert "os.environ" not in source
    assert "os.getenv" not in source
    assert "streamlit" not in source.lower()
    assert "secrets" not in source.lower()
    assert is_dev_diagnostics_enabled() is False
    assert is_dev_diagnostics_enabled(env={"ENABLE_NEWS_DIAGNOSTICS": "1"}) is True


def test_disabled_wrapper_does_not_process_envelopes_or_call_streamlit(monkeypatch):
    class ForbiddenEnvelopes:
        def __iter__(self):
            pytest.fail("disabled wrapper must not process envelopes")

    monkeypatch.setattr(
        news_diagnostics,
        "render_news_schema_diagnostics",
        lambda *args, **kwargs: pytest.fail("disabled wrapper must not render"),
    )
    monkeypatch.setattr(
        news_diagnostics.st,
        "dataframe",
        lambda *args, **kwargs: pytest.fail("disabled wrapper must not call Streamlit"),
    )

    assert render_news_schema_diagnostics_if_enabled(ForbiddenEnvelopes()) is None


def test_enabled_wrapper_delegates_to_diagnostics_renderer(monkeypatch):
    envelopes = [{"title": "Diagnostic"}]
    calls = []
    monkeypatch.setattr(
        news_diagnostics,
        "render_news_schema_diagnostics",
        lambda value: calls.append(value) or "rendered",
    )

    result = render_news_schema_diagnostics_if_enabled(
        envelopes,
        enabled=True,
        language="es",
    )

    assert result == "rendered"
    assert calls == [envelopes]


def test_gate_and_wrapper_have_no_provider_cache_or_openai_dependencies():
    gate_source = inspect.getsource(inspect.getmodule(is_dev_diagnostics_enabled))
    wrapper_source = inspect.getsource(render_news_schema_diagnostics_if_enabled)

    for forbidden in ("providers", "cache_data", "cache_resource", "OpenAI", "requests", "yfinance"):
        assert forbidden not in gate_source
        assert forbidden not in wrapper_source
