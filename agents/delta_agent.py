from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence

from core.database import Database, StoredCandle


@dataclass(slots=True, frozen=True)
class DeltaSignal:
    symbol: str
    timeframe: str
    signal: bool
    signal_type: str
    k_value: float
    confidence: float
    direction: str
    timestamp: str
    roc_price: float

    def as_dict(self) -> dict[str, str | float | bool]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "signal": self.signal,
            "signal_type": self.signal_type,
            "k": self.k_value,
            "k_value": self.k_value,
            "confidence": self.confidence,
            "direction": self.direction,
            "timestamp": self.timestamp,
            "roc_price": self.roc_price,
        }


@dataclass(slots=True, frozen=True)
class HistoricalDeltaSignal:
    symbol: str
    timeframe: str
    open_time: str
    entry_price: float
    roc_price: float
    k: float
    signal: bool
    signal_type: str
    confidence: float
    direction: str

    def as_dict(self) -> dict[str, str | float | bool]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "open_time": self.open_time,
            "entry_price": self.entry_price,
            "roc_price": self.roc_price,
            "k": self.k,
            "signal": self.signal,
            "signal_type": self.signal_type,
            "confidence": self.confidence,
            "direction": self.direction,
        }


@dataclass(slots=True, frozen=True)
class DeltaWindowSummary:
    requested_window: int
    candles_used: int
    complete_window: bool
    total_points: int
    signal_count: int
    signal_percentage: float
    last_k: float

    def as_dict(self) -> dict[str, int | float | bool]:
        return {
            "requested_window": self.requested_window,
            "candles_used": self.candles_used,
            "complete_window": self.complete_window,
            "total_points": self.total_points,
            "signal_count": self.signal_count,
            "signal_percentage": self.signal_percentage,
            "last_k": self.last_k,
        }


class DeltaAgent:
    def __init__(self, database: Database, threshold: float = 0.5) -> None:
        self._database = database
        self._threshold = threshold

    def evaluate(self, symbol: str, timeframe: str) -> dict[str, str | float | bool]:
        candles = self._database.get_recent_candles(symbol=symbol, timeframe=timeframe, limit=2)
        if len(candles) < 2:
            return DeltaSignal(
                symbol=symbol,
                timeframe=timeframe,
                signal=False,
                signal_type="NONE",
                k_value=0.0,
                confidence=0.0,
                direction="NONE",
                timestamp=datetime.now(timezone.utc).isoformat(),
                roc_price=0.0,
            ).as_dict()

        previous_candle, current_candle = candles[-2], candles[-1]
        roc_price, _, k, direction = self._calculate_signal_metrics(previous_candle, current_candle)
        signal = self._is_long_signal(roc_price=roc_price, k=k)
        signal_type = self._resolve_signal_type(roc_price=roc_price, k=k)

        return DeltaSignal(
            symbol=symbol,
            timeframe=timeframe,
            signal=signal,
            signal_type=signal_type,
            k_value=round(k, 6),
            confidence=self._calculate_confidence(k),
            direction=signal_type,
            timestamp=current_candle.close_time,
            roc_price=round(roc_price, 6),
        ).as_dict()

    def evaluate_windows(
        self,
        symbol: str,
        timeframe: str,
        windows: Sequence[int] = (10, 20, 50),
    ) -> dict[str, str | float | int | list[dict[str, int | float | bool]]]:
        summaries: list[DeltaWindowSummary] = []

        for window in windows:
            candles = self._database.get_recent_candles(symbol=symbol, timeframe=timeframe, limit=window)
            summaries.append(self._evaluate_window(candles=candles, requested_window=window))

        total_points = sum(summary.total_points for summary in summaries)
        total_signals = sum(summary.signal_count for summary in summaries)
        signal_percentage = round((total_signals / total_points) * 100, 2) if total_points else 0.0

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "threshold": self._threshold,
            "total_signals": total_signals,
            "total_points": total_points,
            "signal_percentage": signal_percentage,
            "windows": [summary.as_dict() for summary in summaries],
        }

    def get_historical_signals(self, symbol: str, timeframe: str) -> list[HistoricalDeltaSignal]:
        candles = self._database.get_candles(symbol=symbol, timeframe=timeframe)
        if len(candles) < 2:
            return []

        signals: list[HistoricalDeltaSignal] = []
        for previous_candle, current_candle in zip(candles, candles[1:]):
            roc_price, _, k, direction = self._calculate_signal_metrics(previous_candle, current_candle)
            signal = self._is_long_signal(roc_price=roc_price, k=k)
            signal_type = self._resolve_signal_type(roc_price=roc_price, k=k)
            signals.append(
                HistoricalDeltaSignal(
                    symbol=symbol,
                    timeframe=timeframe,
                    open_time=current_candle.open_time,
                    entry_price=current_candle.close,
                    roc_price=round(roc_price, 6),
                    k=round(k, 6),
                    signal=signal,
                    signal_type=signal_type,
                    confidence=self._calculate_confidence(k),
                    direction=signal_type,
                )
            )
        return signals

    @staticmethod
    def _calculate_roc(previous_value: float, current_value: float) -> float:
        if previous_value == 0:
            return 0.0
        return ((current_value - previous_value) / previous_value) * 100

    def _evaluate_window(
        self,
        candles: Sequence[StoredCandle],
        requested_window: int,
    ) -> DeltaWindowSummary:
        if len(candles) < 2:
            return DeltaWindowSummary(
                requested_window=requested_window,
                candles_used=len(candles),
                complete_window=len(candles) >= requested_window,
                total_points=0,
                signal_count=0,
                signal_percentage=0.0,
                last_k=0.0,
            )

        metrics = [self._calculate_signal_metrics(previous, current) for previous, current in zip(candles, candles[1:])]
        k_values = [k for _, _, k, _ in metrics]
        signal_count = sum(1 for roc_price, _, k, _ in metrics if self._is_long_signal(roc_price=roc_price, k=k))
        total_points = len(k_values)
        signal_percentage = round((signal_count / total_points) * 100, 2) if total_points else 0.0

        return DeltaWindowSummary(
            requested_window=requested_window,
            candles_used=len(candles),
            complete_window=len(candles) >= requested_window,
            total_points=total_points,
            signal_count=signal_count,
            signal_percentage=signal_percentage,
            last_k=round(k_values[-1], 6),
        )

    def _calculate_k(self, previous_candle: StoredCandle, current_candle: StoredCandle) -> float:
        _, _, k, _ = self._calculate_signal_metrics(previous_candle, current_candle)
        return k

    def _calculate_signal_metrics(
        self,
        previous_candle: StoredCandle,
        current_candle: StoredCandle,
    ) -> tuple[float, float, float, str]:
        roc_price = self._calculate_roc(previous_candle.close, current_candle.close)
        roc_volume = self._calculate_roc(previous_candle.volume, current_candle.volume)
        direction = self._resolve_direction(roc_price)
        k = abs(roc_price) * roc_volume
        return roc_price, roc_volume, k, direction

    def _is_long_signal(self, *, roc_price: float, k: float) -> bool:
        return roc_price > 0 and k > self._threshold

    def _resolve_signal_type(self, *, roc_price: float, k: float) -> str:
        if k <= self._threshold:
            return "NONE"
        if roc_price > 0:
            return "LONG"
        if roc_price < 0:
            return "SHORT"
        return "NONE"

    def _calculate_confidence(self, k: float) -> float:
        if self._threshold <= 0:
            return 1.0
        normalized = k / (self._threshold * 2)
        return round(max(0.0, min(normalized, 1.0)), 6)

    @staticmethod
    def _resolve_direction(roc_price: float) -> str:
        if roc_price > 0:
            return "LONG"
        if roc_price < 0:
            return "SHORT"
        return "NONE"
