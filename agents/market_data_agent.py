from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Sequence

from data.binance_market_data import Candle


@dataclass(slots=True, frozen=True)
class MarketDataAssessment:
    symbol: str
    timeframe: str
    vote: str
    confidence: float
    provider_used: str
    is_valid: bool
    is_stale: bool
    gap_count: int
    duplicate_count: int
    corrupted_count: int
    notes: tuple[str, ...]

    def as_dict(self) -> dict[str, str | float | bool | int | tuple[str, ...]]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "vote": self.vote,
            "confidence": self.confidence,
            "provider_used": self.provider_used,
            "is_valid": self.is_valid,
            "is_stale": self.is_stale,
            "gap_count": self.gap_count,
            "duplicate_count": self.duplicate_count,
            "corrupted_count": self.corrupted_count,
            "notes": self.notes,
        }


class MarketDataAgent:
    def assess(self, *, symbol: str, timeframe: str, candles: Sequence[Candle], provider_used: str) -> MarketDataAssessment:
        if not candles:
            return MarketDataAssessment(
                symbol=symbol,
                timeframe=timeframe,
                vote="REJECT",
                confidence=0.0,
                provider_used=provider_used,
                is_valid=False,
                is_stale=True,
                gap_count=0,
                duplicate_count=0,
                corrupted_count=0,
                notes=("no candles available",),
            )

        expected_delta = timedelta(seconds=self._timeframe_seconds(timeframe))
        gap_count = 0
        duplicate_count = 0
        corrupted_count = 0
        notes: list[str] = []
        seen_open_times: set[str] = set()

        previous_open_dt: datetime | None = None
        for candle in candles:
            open_dt = datetime.fromisoformat(candle.open_time)
            if candle.open_time in seen_open_times:
                duplicate_count += 1
            seen_open_times.add(candle.open_time)

            if min(candle.open, candle.high, candle.low, candle.close) <= 0 or candle.high < candle.low:
                corrupted_count += 1

            if previous_open_dt is not None and (open_dt - previous_open_dt) > expected_delta:
                gap_count += 1
            previous_open_dt = open_dt

        latest_close_dt = datetime.fromisoformat(candles[-1].close_time)
        now_dt = datetime.now(timezone.utc)
        stale_threshold = expected_delta * 2
        is_stale = (now_dt - latest_close_dt) > stale_threshold

        if gap_count:
            notes.append(f"detected {gap_count} candle gaps")
        if duplicate_count:
            notes.append(f"detected {duplicate_count} duplicate candles")
        if corrupted_count:
            notes.append(f"detected {corrupted_count} corrupted candles")
        if is_stale:
            notes.append("latest candle is stale")

        is_valid = duplicate_count == 0 and corrupted_count == 0 and not is_stale
        if is_valid and gap_count == 0:
            notes.append("market data passed freshness and integrity checks")

        return MarketDataAssessment(
            symbol=symbol,
            timeframe=timeframe,
            vote="OK" if is_valid else "REJECT",
            confidence=0.9 if is_valid else 0.2,
            provider_used=provider_used,
            is_valid=is_valid,
            is_stale=is_stale,
            gap_count=gap_count,
            duplicate_count=duplicate_count,
            corrupted_count=corrupted_count,
            notes=tuple(notes),
        )

    @staticmethod
    def _timeframe_seconds(timeframe: str) -> int:
        raw = timeframe.strip().lower()
        if raw.endswith("m"):
            return int(raw[:-1]) * 60
        if raw.endswith("h"):
            return int(raw[:-1]) * 3600
        return 60
