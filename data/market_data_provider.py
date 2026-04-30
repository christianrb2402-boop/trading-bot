from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol, Sequence

from core.database import Database, StoredCandle
from core.exceptions import ExternalServiceError
from data.binance_market_data import BinanceMarketDataService, Candle


class MarketDataProvider(Protocol):
    name: str

    def fetch_latest_closed_candles(self, symbol: str, timeframe: str, limit: int = 20) -> list[Candle]:
        ...


@dataclass(slots=True, frozen=True)
class ProviderFetchResult:
    provider_used: str
    candles: list[Candle]
    used_fallback: bool
    error_message: str | None = None


class BinanceProvider:
    name = "BINANCE"

    def __init__(self, service: BinanceMarketDataService) -> None:
        self._service = service

    def fetch_latest_closed_candles(self, symbol: str, timeframe: str, limit: int = 20) -> list[Candle]:
        candles = self._service.fetch_latest_closed_candles(symbol=symbol, timeframe=timeframe, limit=limit)
        return [self._with_provider(candle) for candle in candles]

    def _with_provider(self, candle: Candle) -> Candle:
        return Candle(
            symbol=candle.symbol,
            timeframe=candle.timeframe,
            open_time=candle.open_time,
            open=candle.open,
            high=candle.high,
            low=candle.low,
            close=candle.close,
            volume=candle.volume,
            close_time=candle.close_time,
            provider=self.name,
        )


class FutureYahooProvider:
    name = "YAHOO_PLACEHOLDER"

    def fetch_latest_closed_candles(self, symbol: str, timeframe: str, limit: int = 20) -> list[Candle]:
        return []


class LocalSQLiteProvider:
    name = "LOCAL_SQLITE"

    def __init__(self, database: Database) -> None:
        self._database = database

    def fetch_latest_closed_candles(self, symbol: str, timeframe: str, limit: int = 20) -> list[Candle]:
        candles = self._database.get_recent_candles(symbol=symbol, timeframe=timeframe, limit=limit)
        if candles:
            return [self._to_candle(candle) for candle in candles]
        if timeframe == "1m":
            return []
        base_limit = max(limit * self._timeframe_minutes(timeframe), limit)
        base_candles = self._database.get_recent_candles(symbol=symbol, timeframe="1m", limit=base_limit)
        materialized = self._materialize_timeframe(symbol=symbol, timeframe=timeframe, candles=base_candles)
        return [self._to_candle(candle) for candle in materialized[-limit:]]

    @staticmethod
    def _timeframe_minutes(timeframe: str) -> int:
        raw = timeframe.strip().lower()
        if raw.endswith("m"):
            return max(1, int(raw[:-1]))
        if raw.endswith("h"):
            return max(1, int(raw[:-1])) * 60
        return 1

    def _materialize_timeframe(self, *, symbol: str, timeframe: str, candles: Sequence[StoredCandle]) -> list[StoredCandle]:
        minutes = self._timeframe_minutes(timeframe)
        if minutes <= 1:
            return list(candles)
        buckets: list[list[StoredCandle]] = []
        current_bucket: list[StoredCandle] = []
        current_bucket_start: datetime | None = None
        for candle in candles:
            open_dt = datetime.fromisoformat(candle.open_time)
            bucket_start = open_dt.replace(second=0, microsecond=0) - timedelta(minutes=open_dt.minute % minutes)
            if current_bucket_start is None or bucket_start != current_bucket_start:
                if current_bucket:
                    buckets.append(current_bucket)
                current_bucket = [candle]
                current_bucket_start = bucket_start
            else:
                current_bucket.append(candle)
        if current_bucket:
            buckets.append(current_bucket)

        materialized: list[StoredCandle] = []
        for bucket in buckets:
            first = bucket[0]
            last = bucket[-1]
            materialized.append(
                StoredCandle(
                    symbol=symbol,
                    timeframe=timeframe,
                    open_time=first.open_time,
                    open=first.open,
                    high=max(item.high for item in bucket),
                    low=min(item.low for item in bucket),
                    close=last.close,
                    volume=sum(item.volume for item in bucket),
                    close_time=last.close_time,
                    provider=self.name,
                )
            )
        return materialized

    def _to_candle(self, candle: StoredCandle) -> Candle:
        return Candle(
            symbol=candle.symbol,
            timeframe=candle.timeframe,
            open_time=candle.open_time,
            open=candle.open,
            high=candle.high,
            low=candle.low,
            close=candle.close,
            volume=candle.volume,
            close_time=candle.close_time,
            provider=self.name,
        )


class ProviderRouter:
    def __init__(
        self,
        *,
        primary: MarketDataProvider,
        fallbacks: Sequence[MarketDataProvider],
    ) -> None:
        self._primary = primary
        self._fallbacks = tuple(fallbacks)

    def fetch_latest_closed_candles(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 20,
        *,
        prefer_fallback: bool = False,
    ) -> ProviderFetchResult:
        if prefer_fallback:
            for fallback in self._fallbacks:
                candles = fallback.fetch_latest_closed_candles(symbol=symbol, timeframe=timeframe, limit=limit)
                if candles:
                    return ProviderFetchResult(provider_used=fallback.name, candles=candles, used_fallback=True, error_message="Fallback preferred for bounded test mode")
            fallback_name = self._fallbacks[0].name if self._fallbacks else self._primary.name
            return ProviderFetchResult(
                provider_used=fallback_name,
                candles=[],
                used_fallback=True,
                error_message="Fallback preferred for bounded test mode but no local candles were available",
            )
        try:
            candles = self._primary.fetch_latest_closed_candles(symbol=symbol, timeframe=timeframe, limit=limit)
            if candles:
                return ProviderFetchResult(provider_used=self._primary.name, candles=candles, used_fallback=False)
        except ExternalServiceError as exc:
            primary_error = str(exc)
        else:
            primary_error = "Primary provider returned no candles"

        for fallback in self._fallbacks:
            candles = fallback.fetch_latest_closed_candles(symbol=symbol, timeframe=timeframe, limit=limit)
            if candles:
                return ProviderFetchResult(
                    provider_used=fallback.name,
                    candles=candles,
                    used_fallback=True,
                    error_message=primary_error,
                )

        return ProviderFetchResult(
            provider_used=self._primary.name,
            candles=[],
            used_fallback=True,
            error_message=primary_error,
        )
