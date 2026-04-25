from __future__ import annotations

from datetime import datetime, timezone
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from core.exceptions import ExternalServiceError
from core.settings import Settings


class BinanceClient:
    """Cliente minimo para endpoints publicos de Binance."""

    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.binance_base_url
        self._timeout = settings.binance_timeout_seconds

    def get_ticker_price(self, symbol: str) -> float:
        payload = self._get_json("/api/v3/ticker/price", {"symbol": symbol})
        return float(payload["price"])

    def get_latest_kline(self, symbol: str, interval: str) -> dict[str, str]:
        payload = self._get_json(
            "/api/v3/klines",
            {
                "symbol": symbol,
                "interval": interval,
                "limit": 1,
            },
        )
        if not payload:
            raise ExternalServiceError(f"No se recibieron velas para {symbol} en {interval}")

        candle = payload[0]
        return {
            "open_time": datetime.fromtimestamp(candle[0] / 1000, tz=timezone.utc).isoformat(),
            "open_price": candle[1],
            "high_price": candle[2],
            "low_price": candle[3],
            "close_price": candle[4],
            "volume": candle[5],
        }

    def _get_json(self, path: str, params: dict[str, str | int]) -> dict | list:
        query = urlencode(params)
        url = f"{self._base_url}{path}?{query}"
        request = Request(url, headers={"User-Agent": "multiagent-trading-system/0.1"})

        try:
            with urlopen(request, timeout=self._timeout) as response:
                raw_payload = response.read().decode("utf-8")
                return json.loads(raw_payload)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise ExternalServiceError(f"Error consultando Binance: {exc}") from exc

