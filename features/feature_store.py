from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence
import json

from config.settings import Settings
from core.database import Database, FeatureSnapshotRecord, StoredCandle


@dataclass(slots=True, frozen=True)
class FeatureSnapshot:
    symbol: str
    timeframe: str
    timestamp: str
    quality_score: float
    provider: str
    payload: dict[str, object]

    def as_dict(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "timestamp": self.timestamp,
            "quality_score": self.quality_score,
            "provider": self.provider,
            **self.payload,
        }


class FeatureStore:
    def __init__(self, database: Database, settings: Settings) -> None:
        self._database = database
        self._settings = settings

    def build(
        self,
        *,
        symbol: str,
        timeframe: str,
        candles: Sequence[StoredCandle],
        quality_score: float,
        provider: str,
    ) -> FeatureSnapshot:
        if not candles:
            snapshot = FeatureSnapshot(
                symbol=symbol,
                timeframe=timeframe,
                timestamp="",
                quality_score=0.0,
                provider=provider,
                payload={"reason": "no candles available"},
            )
            self._persist(snapshot)
            return snapshot

        closes = [c.close for c in candles]
        highs = [c.high for c in candles]
        lows = [c.low for c in candles]
        volumes = [c.volume for c in candles]
        last = candles[-1]
        ema9 = self._ema(closes, 9)
        ema21 = self._ema(closes, 21)
        ema50 = self._ema(closes, 50)
        ema200 = self._ema(closes, 200)
        roc = self._roc(closes[-2], closes[-1]) if len(closes) >= 2 else 0.0
        rsi = self._rsi(closes, 14)
        macd_proxy = ema9 - ema21
        atr_pct = self._atr_pct(candles[-14:])
        avg_range_pct = self._avg_range_pct(candles[-14:])
        volatility_relative = atr_pct / max(self._avg_range_pct(candles[-28:-14]) or atr_pct or 1.0, 0.000001)
        avg_volume = sum(volumes[-20:]) / max(len(volumes[-20:]), 1)
        relative_volume = (volumes[-1] / avg_volume) if avg_volume else 0.0
        volume_spike = relative_volume >= 1.5
        body_pct = abs(last.close - last.open) / max(last.open, 0.000001) * 100
        upper_wick_pct = (last.high - max(last.open, last.close)) / max(last.open, 0.000001) * 100
        lower_wick_pct = (min(last.open, last.close) - last.low) / max(last.open, 0.000001) * 100
        candle_strength = body_pct - (upper_wick_pct + lower_wick_pct)
        ema_slope_9 = self._slope(closes[-9:]) if len(closes) >= 9 else 0.0
        ema_slope_21 = self._slope(closes[-21:]) if len(closes) >= 21 else 0.0
        structure = self._structure(highs[-5:], lows[-5:]) if len(highs) >= 5 else "UNKNOWN"
        compression = "COMPRESSION" if atr_pct <= avg_range_pct * 0.85 else "EXPANSION" if atr_pct >= avg_range_pct * 1.15 else "STABLE"
        spread_estimated_pct = self._settings.simulated_spread_pct * 100
        slippage_estimated_pct = self._settings.simulated_slippage_pct * 100
        break_even_move_pct = (self._settings.simulated_taker_fee_pct * 2 + self._settings.simulated_spread_pct + (self._settings.simulated_slippage_pct * 2)) * 100
        required_net_move_pct = break_even_move_pct + self._settings.min_expected_net_edge_pct
        estimated_cost_drag = break_even_move_pct / max(abs(roc), 0.000001)

        payload = {
            "ema_9": round(ema9, 6),
            "ema_21": round(ema21, 6),
            "ema_50": round(ema50, 6),
            "ema_200": round(ema200, 6),
            "ema_slope_9": round(ema_slope_9, 6),
            "ema_slope_21": round(ema_slope_21, 6),
            "distance_to_ema_9_pct": round(self._distance_pct(last.close, ema9), 6),
            "distance_to_ema_21_pct": round(self._distance_pct(last.close, ema21), 6),
            "distance_to_ema_50_pct": round(self._distance_pct(last.close, ema50), 6),
            "distance_to_ema_200_pct": round(self._distance_pct(last.close, ema200), 6),
            "structure": structure,
            "rsi": round(rsi, 6),
            "roc": round(roc, 6),
            "macd_proxy": round(macd_proxy, 6),
            "candle_strength": round(candle_strength, 6),
            "acceleration": round(roc - self._roc(closes[-3], closes[-2]) if len(closes) >= 3 else 0.0, 6),
            "atr_pct": round(atr_pct, 6),
            "avg_range_pct": round(avg_range_pct, 6),
            "compression_state": compression,
            "volatility_relative": round(volatility_relative, 6),
            "avg_volume": round(avg_volume, 6),
            "relative_volume": round(relative_volume, 6),
            "volume_spike": volume_spike,
            "body_pct": round(body_pct, 6),
            "upper_wick_pct": round(upper_wick_pct, 6),
            "lower_wick_pct": round(lower_wick_pct, 6),
            "breakout_candle": body_pct > 0.25 and volume_spike,
            "rejection_candle": max(upper_wick_pct, lower_wick_pct) > body_pct,
            "spread_estimated_pct": round(spread_estimated_pct, 6),
            "slippage_estimated_pct": round(slippage_estimated_pct, 6),
            "break_even_move_pct": round(break_even_move_pct, 6),
            "required_net_move_pct": round(required_net_move_pct, 6),
            "estimated_cost_drag": round(estimated_cost_drag, 6),
        }
        snapshot = FeatureSnapshot(
            symbol=symbol,
            timeframe=timeframe,
            timestamp=last.close_time,
            quality_score=round(quality_score, 6),
            provider=provider,
            payload=payload,
        )
        self._persist(snapshot)
        return snapshot

    def _persist(self, snapshot: FeatureSnapshot) -> None:
        self._database.insert_feature_snapshot(
            FeatureSnapshotRecord(
                timestamp=snapshot.timestamp,
                symbol=snapshot.symbol,
                timeframe=snapshot.timeframe,
                feature_payload=json.dumps(snapshot.payload, ensure_ascii=True),
                quality_score=snapshot.quality_score,
                provider=snapshot.provider,
            )
        )

    @staticmethod
    def _ema(values: Sequence[float], period: int) -> float:
        if not values:
            return 0.0
        trimmed = list(values[-period:]) if len(values) >= period else list(values)
        multiplier = 2 / (len(trimmed) + 1)
        ema_value = trimmed[0]
        for value in trimmed[1:]:
            ema_value = (value - ema_value) * multiplier + ema_value
        return ema_value

    @staticmethod
    def _roc(previous_value: float, current_value: float) -> float:
        if previous_value == 0:
            return 0.0
        return ((current_value - previous_value) / previous_value) * 100

    @staticmethod
    def _rsi(values: Sequence[float], period: int) -> float:
        if len(values) < 2:
            return 50.0
        deltas = [values[index] - values[index - 1] for index in range(1, len(values))]
        gains = [delta for delta in deltas[-period:] if delta > 0]
        losses = [-delta for delta in deltas[-period:] if delta < 0]
        avg_gain = sum(gains) / max(period, 1)
        avg_loss = sum(losses) / max(period, 1)
        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 50.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    @staticmethod
    def _atr_pct(candles: Sequence[StoredCandle]) -> float:
        if len(candles) < 2:
            return 0.0
        ranges: list[float] = []
        previous_close = candles[0].close
        for candle in candles[1:]:
            tr = max(candle.high - candle.low, abs(candle.high - previous_close), abs(candle.low - previous_close))
            ranges.append((tr / max(previous_close, 0.000001)) * 100)
            previous_close = candle.close
        return sum(ranges) / len(ranges) if ranges else 0.0

    @staticmethod
    def _avg_range_pct(candles: Sequence[StoredCandle]) -> float:
        if not candles:
            return 0.0
        values = [((c.high - c.low) / max(c.open, 0.000001)) * 100 for c in candles]
        return sum(values) / len(values)

    @staticmethod
    def _distance_pct(price: float, average: float) -> float:
        if average == 0:
            return 0.0
        return ((price - average) / average) * 100

    @staticmethod
    def _slope(values: Sequence[float]) -> float:
        if len(values) < 2:
            return 0.0
        return values[-1] - values[0]

    @staticmethod
    def _structure(highs: Sequence[float], lows: Sequence[float]) -> str:
        if len(highs) < 3 or len(lows) < 3:
            return "UNKNOWN"
        if highs[-1] > highs[0] and lows[-1] > lows[0]:
            return "HIGHER_HIGHS_HIGHER_LOWS"
        if highs[-1] < highs[0] and lows[-1] < lows[0]:
            return "LOWER_HIGHS_LOWER_LOWS"
        return "MIXED"
