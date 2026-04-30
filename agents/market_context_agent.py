from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from core.database import Database, StoredCandle


@dataclass(slots=True, frozen=True)
class MarketContextSnapshot:
    symbol: str
    timeframe: str
    trend_direction: str
    volatility_regime: str
    momentum_strength: float
    momentum_confirmed: bool
    volatility_pct: float
    volume_ratio: float
    volume_spike: bool
    volume_regime: str
    market_regime: str
    compression_state: str
    regime_transition: str
    macro_regime: str
    risk_regime: str
    context_score: float
    reason: str
    candle_count: int

    def as_dict(self) -> dict[str, str | float | bool | int]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "trend_direction": self.trend_direction,
            "volatility_regime": self.volatility_regime,
            "momentum_strength": self.momentum_strength,
            "momentum_confirmed": self.momentum_confirmed,
            "volatility_pct": self.volatility_pct,
            "volume_ratio": self.volume_ratio,
            "volume_spike": self.volume_spike,
            "volume_regime": self.volume_regime,
            "market_regime": self.market_regime,
            "compression_state": self.compression_state,
            "regime_transition": self.regime_transition,
            "macro_regime": self.macro_regime,
            "risk_regime": self.risk_regime,
            "context_score": self.context_score,
            "reason": self.reason,
            "candle_count": self.candle_count,
        }


class MarketContextAgent:
    def __init__(self, database: Database, lookback: int = 20) -> None:
        self._database = database
        self._lookback = lookback

    def evaluate(
        self,
        *,
        symbol: str,
        timeframe: str,
        candles: Sequence[StoredCandle] | None = None,
    ) -> dict[str, str | float | bool | int]:
        recent_candles = list(candles) if candles is not None else self._database.get_recent_candles(
            symbol=symbol,
            timeframe=timeframe,
            limit=self._lookback,
        )
        if len(recent_candles) < 5:
            return MarketContextSnapshot(
                symbol=symbol,
                timeframe=timeframe,
                trend_direction="SIDEWAYS",
                volatility_regime="LOW",
                momentum_strength=0.0,
                momentum_confirmed=False,
                volatility_pct=0.0,
                volume_ratio=0.0,
                volume_spike=False,
                volume_regime="NORMAL",
                market_regime="RANGING",
                compression_state="UNKNOWN",
                regime_transition="UNKNOWN",
                macro_regime="UNKNOWN",
                risk_regime="UNKNOWN",
                context_score=0.0,
                reason="Insufficient candle history for market context analysis",
                candle_count=len(recent_candles),
            ).as_dict()

        first_candle = recent_candles[0]
        latest_candle = recent_candles[-1]
        price_change_pct = self._percent_change(first_candle.close, latest_candle.close)
        previous_volumes = [candle.volume for candle in recent_candles[:-1] if candle.volume > 0]
        avg_volume = (sum(previous_volumes) / len(previous_volumes)) if previous_volumes else latest_candle.volume
        volume_ratio = (latest_candle.volume / avg_volume) if avg_volume else 1.0
        momentum_strength = abs(price_change_pct) * max(volume_ratio, 1.0)
        volatility_pct = self._average_true_range_pct(recent_candles)
        previous_volatility_pct = self._average_true_range_pct(recent_candles[:-1]) if len(recent_candles) > 5 else volatility_pct
        volatility_regime = self._volatility_regime(volatility_pct)
        volume_regime = "SPIKE" if volume_ratio >= 1.5 else "NORMAL"

        if abs(price_change_pct) <= max(volatility_pct * 0.7, 0.05):
            trend_direction = "SIDEWAYS"
        elif price_change_pct > 0:
            trend_direction = "UP"
        else:
            trend_direction = "DOWN"

        momentum_confirmed = abs(price_change_pct) >= max(volatility_pct * 0.8, 0.08) and volume_ratio >= 1.0
        volume_spike = volume_ratio >= 1.5
        market_regime = "TRENDING" if trend_direction != "SIDEWAYS" and momentum_confirmed else "RANGING"
        if volatility_pct <= previous_volatility_pct * 0.85:
            compression_state = "COMPRESSION"
        elif volatility_pct >= previous_volatility_pct * 1.15:
            compression_state = "EXPANSION"
        else:
            compression_state = "STABLE"
        if market_regime == "TRENDING" and previous_volatility_pct < volatility_pct and trend_direction != "SIDEWAYS":
            regime_transition = "RANGE_TO_TREND"
        elif market_regime == "RANGING" and previous_volatility_pct > volatility_pct:
            regime_transition = "TREND_TO_RANGE"
        else:
            regime_transition = "STABLE"
        risk_regime = f"{volatility_regime}_VOL"
        context_score = min(1.0, max(0.0, (momentum_strength / 5.0) + (0.15 if volume_spike else 0.0)))

        reason_parts = [
            f"Trend is {trend_direction} from {round(price_change_pct, 4)}% price change",
            f"momentum strength is {round(momentum_strength, 4)} with volume ratio {round(volume_ratio, 4)}",
            f"volatility is {round(volatility_pct, 4)}%",
            f"volatility regime is {volatility_regime}",
            f"volume regime is {volume_regime}",
            f"market regime classified as {market_regime}",
            f"compression state is {compression_state}",
            f"regime transition is {regime_transition}",
        ]
        if volume_spike:
            reason_parts.append("latest volume qualifies as a spike")
        if not momentum_confirmed:
            reason_parts.append("momentum confirmation is weak")

        return MarketContextSnapshot(
            symbol=symbol,
            timeframe=timeframe,
            trend_direction=trend_direction,
            volatility_regime=volatility_regime,
            momentum_strength=round(momentum_strength, 6),
            momentum_confirmed=momentum_confirmed,
            volatility_pct=round(volatility_pct, 6),
            volume_ratio=round(volume_ratio, 6),
            volume_spike=volume_spike,
            volume_regime=volume_regime,
            market_regime=market_regime,
            compression_state=compression_state,
            regime_transition=regime_transition,
            macro_regime=trend_direction,
            risk_regime=risk_regime,
            context_score=round(context_score, 6),
            reason="; ".join(reason_parts),
            candle_count=len(recent_candles),
        ).as_dict()

    @staticmethod
    def _percent_change(start_value: float, end_value: float) -> float:
        if start_value == 0:
            return 0.0
        return ((end_value - start_value) / start_value) * 100

    @staticmethod
    def _average_true_range_pct(candles: Sequence[StoredCandle]) -> float:
        if len(candles) < 2:
            return 0.0

        true_ranges: list[float] = []
        previous_close = candles[0].close
        for candle in candles[1:]:
            high_low = candle.high - candle.low
            high_close = abs(candle.high - previous_close)
            low_close = abs(candle.low - previous_close)
            true_range = max(high_low, high_close, low_close)
            base_price = previous_close if previous_close else candle.close
            true_ranges.append((true_range / base_price) * 100 if base_price else 0.0)
            previous_close = candle.close
        return sum(true_ranges) / len(true_ranges) if true_ranges else 0.0

    @staticmethod
    def _volatility_regime(volatility_pct: float) -> str:
        if volatility_pct >= 0.6:
            return "HIGH"
        if volatility_pct >= 0.15:
            return "NORMAL"
        return "LOW"
