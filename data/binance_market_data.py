from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from config.settings import Settings
from core.exceptions import ExternalServiceError


logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class Candle:
    symbol: str
    timeframe: str
    open_time: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time: str


class BinanceMarketDataService:
    _MAX_KLINES_PER_REQUEST = 1000

    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.binance_base_url
        self._timeout = settings.binance_timeout_seconds

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> list[Candle]:
        if limit <= 0:
            return []

        if limit <= self._MAX_KLINES_PER_REQUEST:
            return self._fetch_ohlcv_batch(symbol=symbol, timeframe=timeframe, limit=limit)

        return self.fetch_ohlcv_history(symbol=symbol, timeframe=timeframe, total_limit=limit)

    def fetch_latest_closed_candles(self, symbol: str, timeframe: str, limit: int = 2) -> list[Candle]:
        batch_limit = max(limit + 2, 4)
        candles = self._fetch_ohlcv_batch(symbol=symbol, timeframe=timeframe, limit=batch_limit)
        now = datetime.now(timezone.utc)
        closed_candles = [candle for candle in candles if datetime.fromisoformat(candle.close_time) <= now]
        return closed_candles[-limit:]

    def fetch_ohlcv_history(self, symbol: str, timeframe: str, total_limit: int) -> list[Candle]:
        logger.info(
            "Fetching historical OHLCV from Binance",
            extra={
                "event": "history_fetch_start",
                "context": {"symbol": symbol, "timeframe": timeframe, "total_limit": total_limit},
            },
        )

        collected: list[Candle] = []
        remaining = total_limit
        end_time_ms: int | None = None
        batch_number = 0

        while remaining > 0:
            batch_number += 1
            batch_limit = min(remaining, self._MAX_KLINES_PER_REQUEST)
            batch = self._fetch_ohlcv_batch(
                symbol=symbol,
                timeframe=timeframe,
                limit=batch_limit,
                end_time_ms=end_time_ms,
            )
            if not batch:
                break

            collected = batch + collected
            remaining -= len(batch)
            end_time_ms = self._to_open_time_ms(batch[0]) - 1

            logger.info(
                "Fetched historical OHLCV batch from Binance",
                extra={
                    "event": "history_fetch_batch",
                    "context": {
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "batch_number": batch_number,
                        "batch_candles": len(batch),
                        "remaining": remaining,
                    },
                },
            )

            if len(batch) < batch_limit:
                break

        candles = self._deduplicate_candles(collected)
        logger.info(
            "Fetched historical OHLCV from Binance",
            extra={
                "event": "history_fetch_success",
                "context": {"symbol": symbol, "timeframe": timeframe, "candles": len(candles)},
            },
        )
        return candles

    def _fetch_ohlcv_batch(
        self,
        *,
        symbol: str,
        timeframe: str,
        limit: int,
        end_time_ms: int | None = None,
    ) -> list[Candle]:
        logger.info(
            "Fetching OHLCV from Binance",
            extra={
                "event": "fetch_start",
                "context": {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "limit": limit,
                    "end_time_ms": end_time_ms,
                },
            },
        )
        params: dict[str, str | int] = {"symbol": symbol, "interval": timeframe, "limit": limit}
        if end_time_ms is not None:
            params["endTime"] = end_time_ms

        payload = self._get_json("/api/v3/klines", params)
        candles = [self._build_candle(symbol, timeframe, item) for item in payload]
        logger.info(
            "Fetched OHLCV from Binance",
            extra={
                "event": "fetch_success",
                "context": {"symbol": symbol, "timeframe": timeframe, "candles": len(candles)},
            },
        )
        return candles

    def _get_json(self, path: str, params: dict[str, str | int]) -> list[list]:
        query = urlencode(params)
        url = f"{self._base_url}{path}?{query}"
        request = Request(url, headers={"User-Agent": "multiagent-trading-system/0.1"})

        try:
            with urlopen(request, timeout=self._timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise ExternalServiceError(f"Error consultando Binance: {exc}") from exc

    @staticmethod
    def _build_candle(symbol: str, timeframe: str, payload: list) -> Candle:
        return Candle(
            symbol=symbol,
            timeframe=timeframe,
            open_time=datetime.fromtimestamp(payload[0] / 1000, tz=timezone.utc).isoformat(),
            open=float(payload[1]),
            high=float(payload[2]),
            low=float(payload[3]),
            close=float(payload[4]),
            volume=float(payload[5]),
            close_time=datetime.fromtimestamp(payload[6] / 1000, tz=timezone.utc).isoformat(),
        )

    @staticmethod
    def _deduplicate_candles(candles: list[Candle]) -> list[Candle]:
        unique_by_open_time: dict[str, Candle] = {}
        for candle in candles:
            unique_by_open_time[candle.open_time] = candle
        return sorted(unique_by_open_time.values(), key=lambda candle: candle.open_time)

    @staticmethod
    def _to_open_time_ms(candle: Candle) -> int:
        return int(datetime.fromisoformat(candle.open_time).timestamp() * 1000)
