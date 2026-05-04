from __future__ import annotations

from agents.trend_following_agent import StrategyProposal


class MomentumScalpAgent:
    name = "MomentumScalpAgent"
    strategy_name = "MOMENTUM_SCALP"

    def evaluate(self, *, symbol: str, timeframe: str, features: dict[str, object], market_state: dict[str, object], direction_bias: str) -> StrategyProposal:
        roc = float(features.get("roc", 0.0))
        rel_vol = float(features.get("relative_volume", 0.0))
        volatility = float(features.get("atr_pct", 0.0))
        decision = "NO_TRADE"
        confidence = 0.16
        if rel_vol >= 1.5 and volatility >= 0.08 and abs(roc) >= 0.08:
            decision = "LONG" if roc > 0 else "SHORT"
            confidence = 0.7
        return StrategyProposal(
            agent_name=self.name,
            strategy_name=self.strategy_name,
            symbol=symbol,
            timeframe=timeframe,
            proposed_decision=decision,
            confidence=confidence,
            expected_move_pct=max(abs(roc) * 1.4, 0.12),
            stop_loss_pct=max(volatility * 0.7, 0.06),
            take_profit_pct=max(abs(roc) * 1.8, 0.14),
            risk_reward_ratio=1.5,
            expected_net_edge_pct=max(abs(roc) * 0.9, 0.0),
            entry_reason="momentum scalp sees quick directional burst with liquidity",
            invalidation_reason="momentum decays or spread dominates the move",
            risk_flags=(() if decision != "NO_TRADE" else ("insufficient_scalp_edge",)),
            raw_payload={"direction_bias": direction_bias, "relative_volume": rel_vol},
        )

