"""Pure development-mode gates supplied entirely by the caller."""


_TRUE_ENV_VALUES = {"1", "true"}


def is_dev_diagnostics_enabled(config: dict | None = None, env: dict | None = None) -> bool:
    """Return whether news diagnostics were explicitly enabled.

    An explicit config value is authoritative. Otherwise, only the caller-supplied
    environment mapping is inspected; the process environment is never read.
    """
    if isinstance(config, dict) and "enable_news_diagnostics" in config:
        return config["enable_news_diagnostics"] is True
    if not isinstance(env, dict):
        return False
    value = env.get("ENABLE_NEWS_DIAGNOSTICS")
    return isinstance(value, str) and value.strip().lower() in _TRUE_ENV_VALUES
