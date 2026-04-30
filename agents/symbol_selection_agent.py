from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from config.settings import Settings
from core.database import StoredCandle


@dataclass(slots=True, frozen=True)
class SymbolSelectionSnapshot:
    symbol: str
    timeframe: str
    symbol_score: float
    liquidity_score: float
    volatility_score: float
    spread_score: float
    data_quality_score: float
    institutional_proxy_score: float
    tradable_today: bool
    reason: str

    def as_dict(self) -> dict[str, str | float | bool]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "symbol_score": self.symbol_score,
            "liquidity_score": self.liquidity_score,
            "volatility_score": self.volatility_score,
            "spread_score": self.spread_score,
            "data_quality_score": self.data_quality_score,
            "institutional_proxy_score": self.institutional_proxy_score,
            "tradable_today": self.tradable_today,
            "reason": self.reason,
        }


class SymbolSelectionAgent:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def evaluate(
        self,
        *,
        symbol: str,
        timeframe: str,
        candles: Sequence[StoredCandle],
        market_context: dict[str, object],
        gap_count: int,
        duplicate_count: int,
        corrupted_count: int,
        estimated_cost_drag_pct: float,
    ) -> SymbolSelectionSnapshot:
        latest = candles[-1] if candles else None
        average_volume = sum(candle.volume for candle in candles[-20:]) / max(len(candles[-20:]), 1) if candles else 0.0
        volume_floor = 50.0 if timeframe in {"1m", "5m", "15m"} else 20.0
        liquidity_score = min(1.0, average_volume / max(volume_floor, 1.0))

        volatility_pct = float(market_context.get("volatility_pct", 0.0))
        if 0.08 <= volatility_pct <= 2.5:
            volatility_score = 1.0
        elif 0.04 <= volatility_pct <= 4.0:
            volatility_score = 0.65
        else:
            volatility_score = 0.25

        spread_pct_estimate = self._settings.simulated_spread_pct * 100
        spread_score = max(0.0, 1.0 - min(spread_pct_estimate / 0.08, 1.0))
        gap_penalty = min(1.0, (gap_count * 0.15) + (duplicate_count * 0.2) + (corrupted_count * 0.25))
        data_quality_score = max(0.0, 1.0 - gap_penalty)

        is_core = symbol in self._settings.core_symbols
        institutional_proxy_score = min(
            1.0,
            (
                (0.35 if is_core else 0.15)
                + (0.25 * liquidity_score)
                + (0.2 * spread_score)
                + (0.2 * data_quality_score)
            ),
        )
        symbol_score = round(
            (
                (0.25 * liquidity_score)
                + (0.2 * volatility_score)
                + (0.15 * spread_score)
                + (0.2 * data_quality_score)
                + (0.2 * institutional_proxy_score)
            ),
            6,
        )

        tradable_today = bool(
            latest
            and len(candles) >= 20
            and gap_count <= 2
            and duplicate_count == 0
            and corrupted_count == 0
            and liquidity_score >= 0.45
            and volatility_score >= 0.4
            and spread_score >= 0.45
            and data_quality_score >= 0.55
            and estimated_cost_drag_pct <= self._settings.max_cost_drag_pct
        )

        reasons: list[str] = []
        if not latest:
            reasons.append("no candle data")
        if len(candles) < 20:
            reasons.append("insufficient candle history")
        if gap_count > 2:
            reasons.append(f"too many gaps ({gap_count})")
        if duplicate_count:
            reasons.append(f"duplicate candles detected ({duplicate_count})")
        if corrupted_count:
            reasons.append(f"corrupted candles detected ({corrupted_count})")
        if liquidity_score < 0.45:
            reasons.append(f"liquidity score too low ({round(liquidity_score, 4)})")
        if volatility_score < 0.4:
            reasons.append(f"volatility not tradable ({round(volatility_pct, 4)}%)")
        if spread_score < 0.45:
            reasons.append(f"spread score too low ({round(spread_score, 4)})")
        if estimated_cost_drag_pct > self._settings.max_cost_drag_pct:
            reasons.append(f"cost drag too high ({round(estimated_cost_drag_pct, 4)}%)")
        if not reasons:
            reasons.append("symbol passed liquidity, cost and data-quality filters")

        return SymbolSelectionSnapshot(
            symbol=symbol,
            timeframe=timeframe,
            symbol_score=symbol_score,
            liquidity_score=round(liquidity_score, 6),
            volatility_score=round(volatility_score, 6),
            spread_score=round(spread_score, 6),
            data_quality_score=round(data_quality_score, 6),
            institutional_proxy_score=round(institutional_proxy_score, 6),
            tradable_today=tradable_today,
            reason="; ".join(reasons),
        )
