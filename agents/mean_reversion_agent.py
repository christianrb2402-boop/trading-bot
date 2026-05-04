from __future__ import annotations

from agents.trend_following_agent import StrategyProposal


class MeanReversionAgent:
    name = "MeanReversionAgent"
    strategy_name = "MEAN_REVERSION"

    def evaluate(self, *, symbol: str, timeframe: str, features: dict[str, object], market_state: dict[str, object], direction_bias: str) -> StrategyProposal:
        rsi = float(features.get("rsi", 50.0))
        distance_ema21 = float(features.get("distance_to_ema_21_pct", 0.0))
        trend = str(market_state.get("trend_state", "SIDEWAYS"))
        decision = "NO_TRADE"
        confidence = 0.2
        if trend == "SIDEWAYS" and rsi <= 35 and distance_ema21 <= -0.2:
            decision = "LONG"
            confidence = 0.66
        elif trend == "SIDEWAYS" and rsi >= 65 and distance_ema21 >= 0.2:
            decision = "SHORT"
            confidence = 0.66
        return StrategyProposal(
            agent_name=self.name,
            strategy_name=self.strategy_name,
            symbol=symbol,
            timeframe=timeframe,
            proposed_decision=decision,
            confidence=confidence,
            expected_move_pct=max(abs(distance_ema21) * 1.8, 0.15),
            stop_loss_pct=max(float(features.get("atr_pct", 0.0)) * 0.8, 0.08),
            take_profit_pct=max(abs(distance_ema21) * 2.3, 0.18),
            risk_reward_ratio=1.7,
            expected_net_edge_pct=max(abs(distance_ema21) * 1.1, 0.0),
            entry_reason="mean reversion sees sideways regime and stretched RSI/distance to mean",
            invalidation_reason="range breaks and move turns into trend",
            risk_flags=(() if decision != "NO_TRADE" else ("range_not_clear",)),
            raw_payload={"direction_bias": direction_bias, "rsi": rsi, "distance_ema21_pct": distance_ema21},
        )

