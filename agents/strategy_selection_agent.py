from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class StrategySelection:
    primary_strategy: str
    secondary_strategy: str
    forbidden_strategies: tuple[str, ...]
    confidence: float
    reason: str

    def as_dict(self) -> dict[str, object]:
        return {
            "primary_strategy": self.primary_strategy,
            "secondary_strategy": self.secondary_strategy,
            "forbidden_strategies": self.forbidden_strategies,
            "confidence": self.confidence,
            "reason": self.reason,
        }


class StrategySelectionAgent:
    def select(
        self,
        *,
        market_state: str,
        risk_mode: str,
        expected_cost_drag: float,
    ) -> StrategySelection:
        forbidden: list[str] = []
        if market_state in {"CHOPPY", "UNKNOWN"} or risk_mode == "DO_NOT_TRADE":
            return StrategySelection("NO_TRADE", "NO_TRADE", ("TREND_FOLLOWING", "BREAKOUT", "MEAN_REVERSION", "MOMENTUM_SCALP", "PULLBACK_CONTINUATION"), 0.0, "state is unsuitable for trading")
        if market_state == "TREND_UP":
            primary = "TREND_FOLLOWING"
            secondary = "PULLBACK_CONTINUATION"
            forbidden.extend(("MEAN_REVERSION",))
        elif market_state == "TREND_DOWN":
            primary = "TREND_FOLLOWING"
            secondary = "PULLBACK_CONTINUATION"
            forbidden.extend(("MEAN_REVERSION",))
        elif market_state == "RANGE":
            primary = "MEAN_REVERSION"
            secondary = "NO_TRADE"
            forbidden.extend(("BREAKOUT",))
        elif market_state in {"BREAKOUT_ATTEMPT", "BREAKOUT_CONFIRMED"}:
            primary = "BREAKOUT"
            secondary = "MOMENTUM_SCALP"
        elif market_state == "COMPRESSION":
            primary = "NO_TRADE"
            secondary = "BREAKOUT"
            forbidden.extend(("MOMENTUM_SCALP",))
        elif market_state == "LOW_VOLATILITY":
            primary = "NO_TRADE"
            secondary = "MEAN_REVERSION"
            forbidden.extend(("MOMENTUM_SCALP",))
        elif market_state == "HIGH_VOLATILITY":
            primary = "BREAKOUT"
            secondary = "TREND_FOLLOWING"
            forbidden.extend(("MOMENTUM_SCALP",))
        else:
            primary = "NO_TRADE"
            secondary = "NO_TRADE"
        if expected_cost_drag > 0.35 and primary in {"MEAN_REVERSION", "MOMENTUM_SCALP"}:
            primary = "NO_TRADE"
            forbidden.append("MOMENTUM_SCALP")
        confidence = 0.75 if primary != "NO_TRADE" else 0.2
        reason = f"selected {primary} with backup {secondary} under market state {market_state} and risk mode {risk_mode}"
        return StrategySelection(primary, secondary, tuple(dict.fromkeys(forbidden)), confidence, reason)

