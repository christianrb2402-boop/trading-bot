from __future__ import annotations

from agents.trend_following_agent import StrategyProposal


class BreakoutAgent:
    name = "BreakoutAgent"
    strategy_name = "BREAKOUT"

    def evaluate(self, *, symbol: str, timeframe: str, features: dict[str, object], market_state: dict[str, object], direction_bias: str) -> StrategyProposal:
        breakout_candle = bool(features.get("breakout_candle", False))
        volume_spike = bool(features.get("volume_spike", False))
        roc = float(features.get("roc", 0.0))
        compression = str(features.get("compression_state", "STABLE"))
        decision = "NO_TRADE"
        confidence = 0.18
        if breakout_candle and volume_spike and compression in {"COMPRESSION", "STABLE"}:
            decision = "LONG" if roc > 0 else "SHORT" if roc < 0 else "NO_TRADE"
            confidence = 0.74
        return StrategyProposal(
            agent_name=self.name,
            strategy_name=self.strategy_name,
            symbol=symbol,
            timeframe=timeframe,
            proposed_decision=decision,
            confidence=confidence,
            expected_move_pct=max(abs(roc) * 2.2, 0.25),
            stop_loss_pct=max(float(features.get("atr_pct", 0.0)), 0.14),
            take_profit_pct=max(abs(roc) * 3.0, 0.35),
            risk_reward_ratio=2.0,
            expected_net_edge_pct=max(abs(roc) * 1.5, 0.0),
            entry_reason="breakout candle with volume spike after compression or stable base",
            invalidation_reason="breakout fails to hold closing range",
            risk_flags=(() if decision != "NO_TRADE" else ("no_confirmed_breakout",)),
            raw_payload={"direction_bias": direction_bias, "compression": compression},
        )

