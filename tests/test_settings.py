from config.settings import load_settings


def test_load_settings_defaults() -> None:
    settings = load_settings()
    assert settings.app_name
    assert settings.sqlite_path.name
    assert settings.market_symbols
    assert settings.market_timeframe == "1m"

