from __future__ import annotations

from dataclasses import dataclass
import json

from config.settings import Settings
from core.database import Database


@dataclass(slots=True, frozen=True)
class MetaLearningAssessment:
    confidence_adjustment: float
    preferred_strategies: tuple[str, ...]
    blocked_strategies: tuple[str, ...]
    agent_reliability: dict[str, float]
    regime_recommendation: str
    symbol_recommendation: str
    sample_strength: str
    reason: str

    def as_dict(self) -> dict[str, object]:
        return {
            "confidence_adjustment": self.confidence_adjustment,
            "preferred_strategies": self.preferred_strategies,
            "blocked_strategies": self.blocked_strategies,
            "agent_reliability": self.agent_reliability,
            "regime_recommendation": self.regime_recommendation,
            "symbol_recommendation": self.symbol_recommendation,
            "sample_strength": self.sample_strength,
            "reason": self.reason,
        }


class MetaLearningAgent:
    def __init__(self, database: Database, settings: Settings) -> None:
        self._database = database
        self._settings = settings

    def assess(
        self,
        *,
        symbol: str,
        timeframe: str,
        strategy_name: str,
        market_state: str,
    ) -> MetaLearningAssessment:
        rows = self._database.get_recent_brain_decisions(limit=200)
        matching = [row for row in rows if row["symbol"] == symbol and row["timeframe"] == timeframe and row["selected_strategy"] == strategy_name]
        sample_size = len(matching)
        if sample_size < 20:
            strength = "WEAK"
            adjustment = 0.0
        elif sample_size < 50:
            strength = "MODERATE"
            adjustment = 0.03
        elif sample_size < 100:
            strength = "USABLE"
            adjustment = 0.06
        elif sample_size < 300:
            strength = "STRONG"
            adjustment = 0.08
        else:
            strength = "VERY_STRONG"
            adjustment = 0.12
        recent_strategy_evals = self._database.get_recent_strategy_evaluations(limit=100)
        preferred = tuple(
            row["strategy_name"]
            for row in recent_strategy_evals
            if row["symbol"] == symbol and row["recommendation"] in {"PREFER", "ALLOW"}
        )[:3]
        blocked = tuple(
            row["strategy_name"]
            for row in recent_strategy_evals
            if row["symbol"] == symbol and row["recommendation"] in {"BLOCK", "AVOID"}
        )[:3]
        agent_rows = self._database.get_recent_agent_performance(limit=100)
        reliability = {row["agent_name"]: float(row["reliability_score"]) for row in agent_rows[:8]}
        if strategy_name in blocked:
            adjustment = min(adjustment, 0.0) - 0.08
        elif strategy_name in preferred:
            adjustment += 0.05
        symbol_recommendation = "PREFER" if strategy_name in preferred else "AVOID" if strategy_name in blocked else "NEUTRAL"
        regime_recommendation = f"prefer {strategy_name} in {market_state}" if strategy_name in preferred else f"use caution in {market_state}"
        return MetaLearningAssessment(
            confidence_adjustment=round(adjustment, 6),
            preferred_strategies=preferred,
            blocked_strategies=blocked,
            agent_reliability=reliability,
            regime_recommendation=regime_recommendation,
            symbol_recommendation=symbol_recommendation,
            sample_strength=strength,
            reason=json.dumps({"sample_size": sample_size, "market_state": market_state}, ensure_ascii=True),
        )

