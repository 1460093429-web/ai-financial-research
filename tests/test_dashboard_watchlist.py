import json

from conftest import import_root_dashboard


dashboard = import_root_dashboard()


def test_load_watchlist_normalizes_deduplicates_and_rejects_invalid_symbols(tmp_path, monkeypatch):
    watchlist_file = tmp_path / "watchlist.json"
    watchlist_file.write_text(
        json.dumps({"tickers": [" nvda ", "NVDA", "mu", "BRK.B", "BAD/TICKER", "", None]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(dashboard, "WATCHLIST_FILE", str(watchlist_file))

    result = dashboard.load_watchlist()

    assert result == ["NVDA", "MU", "BRK.B"]
    assert json.loads(watchlist_file.read_text(encoding="utf-8"))["tickers"] == [
        " nvda ",
        "NVDA",
        "mu",
        "BRK.B",
        "BAD/TICKER",
        "",
        None,
    ]


def test_load_watchlist_missing_file_creates_default_only_at_injected_path(tmp_path, monkeypatch):
    watchlist_file = tmp_path / "nested" / "watchlist.json"
    watchlist_file.parent.mkdir()
    monkeypatch.setattr(dashboard, "WATCHLIST_FILE", str(watchlist_file))

    result = dashboard.load_watchlist()

    assert result == dashboard.DEFAULT_WATCHLIST
    assert json.loads(watchlist_file.read_text(encoding="utf-8")) == {
        "tickers": dashboard.DEFAULT_WATCHLIST
    }


def test_load_watchlist_malformed_payload_resets_to_default_at_injected_path(tmp_path, monkeypatch):
    watchlist_file = tmp_path / "watchlist.json"
    watchlist_file.write_text('{"tickers": "NVDA"}', encoding="utf-8")
    monkeypatch.setattr(dashboard, "WATCHLIST_FILE", str(watchlist_file))

    result = dashboard.load_watchlist()

    assert result == dashboard.DEFAULT_WATCHLIST
    assert json.loads(watchlist_file.read_text(encoding="utf-8")) == {
        "tickers": dashboard.DEFAULT_WATCHLIST
    }
