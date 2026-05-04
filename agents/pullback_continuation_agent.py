from __future__ import annotations

from agents.trend_following_agent import StrategyProposal


class PullbackContinuationAgent:
    name = "PullbackContinuationAgent"
    strategy_name = "PULLBACK_CONTINUATION"

    def evaluate(self, *, symbol: str, timeframe: str, features: dict[str, object], market_state: dict[str, object], direction_bias: str) -> StrategyProposal:
        trend = str(market_state.get("trend_state", "SIDEWAYS"))
        distance_ema9 = float(features.get("distance_to_ema_9_pct", 0.0))
        rsi = float(features.get("rsi", 50.0))
        decision = "NO_TRADE"
        confidence = 0.22
        if trend == "UP" and distance_ema9 <= -0.08 and rsi >= 45:
            decision = "LONG"
            confidence = 0.72
        elif trend == "DOWN" and distance_ema9 >= 0.08 and rsi <= 55:
            decision = "SHORT"
            confidence = 0.72
        return StrategyProposal(
            agent_name=self.name,
            strategy_name=self.strategy_name,
            symbol=symbol,
            timeframe=timeframe,
            proposed_decision=decision,
            confidence=confidence,
            expected_move_pct=max(abs(distance_ema9) * 2.4, 0.18),
            stop_loss_pct=max(float(features.get("atr_pct", 0.0)), 0.09),
            take_profit_pct=max(abs(distance_ema9) * 3.0, 0.25),
            risk_reward_ratio=1.8,
            expected_net_edge_pct=max(abs(distance_ema9) * 1.3, 0.0),
            entry_reason="pullback continuation sees retracement inside prevailing trend",
            invalidation_reason="pullback extends and breaks the trend structure",
            risk_flags=(() if decision != "NO_TRADE" else ("pullback_not_clean",)),
            raw_payload={"direction_bias": direction_bias, "distance_ema9_pct": distance_ema9, "rsi": rsi},
        )

