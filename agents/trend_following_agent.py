from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class StrategyProposal:
    agent_name: str
    strategy_name: str
    symbol: str
    timeframe: str
    proposed_decision: str
    confidence: float
    expected_move_pct: float
    stop_loss_pct: float
    take_profit_pct: float
    risk_reward_ratio: float
    expected_net_edge_pct: float
    entry_reason: str
    invalidation_reason: str
    risk_flags: tuple[str, ...]
    raw_payload: dict[str, object]

    def as_dict(self) -> dict[str, object]:
        return {
            "agent_name": self.agent_name,
            "strategy_name": self.strategy_name,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "proposed_decision": self.proposed_decision,
            "confidence": self.confidence,
            "expected_move_pct": self.expected_move_pct,
            "stop_loss_pct": self.stop_loss_pct,
            "take_profit_pct": self.take_profit_pct,
            "risk_reward_ratio": self.risk_reward_ratio,
            "expected_net_edge_pct": self.expected_net_edge_pct,
            "entry_reason": self.entry_reason,
            "invalidation_reason": self.invalidation_reason,
            "risk_flags": self.risk_flags,
            "raw_payload": self.raw_payload,
        }


class TrendFollowingAgent:
    name = "TrendFollowingAgent"
    strategy_name = "TREND_FOLLOWING"

    def evaluate(self, *, symbol: str, timeframe: str, features: dict[str, object], market_state: dict[str, object], direction_bias: str) -> StrategyProposal:
        ema9 = float(features.get("ema_9", 0.0))
        ema21 = float(features.get("ema_21", 0.0))
        ema50 = float(features.get("ema_50", 0.0))
        structure = str(features.get("structure", "UNKNOWN"))
        rsi = float(features.get("rsi", 50.0))
        relative_volume = float(features.get("relative_volume", 0.0))
        trend = str(market_state.get("trend_state", "SIDEWAYS"))
        direction = "NO_TRADE"
        confidence = 0.2
        if trend == "UP" and ema9 >= ema21 >= ema50 and structure == "HIGHER_HIGHS_HIGHER_LOWS" and rsi >= 52:
            direction = "LONG"
            confidence = 0.78 if relative_volume >= 1.0 else 0.62
        elif trend == "DOWN" and ema9 <= ema21 <= ema50 and structure == "LOWER_HIGHS_LOWER_LOWS" and rsi <= 48:
            direction = "SHORT"
            confidence = 0.78 if relative_volume >= 1.0 else 0.62
        return StrategyProposal(
            agent_name=self.name,
            strategy_name=self.strategy_name,
            symbol=symbol,
            timeframe=timeframe,
            proposed_decision=direction,
            confidence=round(confidence, 6),
            expected_move_pct=max(abs(float(features.get("roc", 0.0))) * 1.8, 0.2),
            stop_loss_pct=max(float(features.get("atr_pct", 0.0)), 0.12),
            take_profit_pct=max(abs(float(features.get("roc", 0.0))) * 2.5, 0.25),
            risk_reward_ratio=1.8,
            expected_net_edge_pct=max(abs(float(features.get("roc", 0.0))) * 1.2, 0.0),
            entry_reason=f"trend following sees {trend} with aligned EMAs and structure {structure}",
            invalidation_reason="EMA alignment breaks or structure fails",
            risk_flags=(() if direction != "NO_TRADE" else ("trend_not_clear",)),
            raw_payload={"direction_bias": direction_bias, "rsi": rsi, "relative_volume": relative_volume},
        )

