from __future__ import annotations

from dataclasses import dataclass

from data.binance_client import BinanceClient


@dataclass(slots=True)
class MarketSnapshot:
    symbol: str
    interval: str
    price: float
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: float
    source_time: str


class MarketDataService:
    def __init__(self, client: BinanceClient) -> None:
        self._client = client

    def read_snapshot(self, symbol: str, interval: str) -> MarketSnapshot:
        latest_price = self._client.get_ticker_price(symbol)
        latest_kline = self._client.get_latest_kline(symbol, interval)

        return MarketSnapshot(
            symbol=symbol,
            interval=interval,
            price=latest_price,
            open_price=float(latest_kline["open_price"]),
            high_price=float(latest_kline["high_price"]),
            low_price=float(latest_kline["low_price"]),
            close_price=float(latest_kline["close_price"]),
            volume=float(latest_kline["volume"]),
            source_time=latest_kline["open_time"],
        )

