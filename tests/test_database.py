from pathlib import Path
from tempfile import TemporaryDirectory

from core.database import Database
from data.binance_market_data import Candle


def test_insert_candles_ignores_duplicates() -> None:
    with TemporaryDirectory() as temp_dir:
        database = Database(Path(temp_dir) / "test.db")
        database.initialize()

        candle = Candle(
            symbol="BTCUSDT",
            timeframe="1m",
            open_time="2026-04-25T00:00:00+00:00",
            open=90000.0,
            high=90100.0,
            low=89900.0,
            close=90050.0,
            volume=12.34,
            close_time="2026-04-25T00:00:59+00:00",
        )

        first_result = database.insert_candles([candle])
        second_result = database.insert_candles([candle])

        assert first_result.inserted == 1
        assert first_result.duplicates == 0
        assert second_result.inserted == 0
        assert second_result.duplicates == 1
        assert database.count_candles("BTCUSDT", "1m") == 1
