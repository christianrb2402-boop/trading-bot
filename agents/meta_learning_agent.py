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
        paper_mode: str,
    ) -> MetaLearningAssessment:
        rows = self._database.get_recent_brain_decisions(limit=200)
        matching = [
            row
            for row in rows
            if row["symbol"] == symbol
            and row["timeframe"] == timeframe
            and row["selected_strategy"] == strategy_name
            and str(row.get("paper_mode") or "OBSERVE_ONLY") == paper_mode
        ]
        sample_size = len(matching)
        minimum_claim_sample = max(self._settings.min_sample_size_for_profitability_claim, 1)
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
            str(row["strategy_name"]).split("|", 1)[0]
            for row in recent_strategy_evals
            if row["symbol"] == symbol and row["recommendation"] in {"PREFER", "ALLOW", "WATCHLIST_POSITIVE"}
        )[:3]
        blocked = tuple(
            str(row["strategy_name"]).split("|", 1)[0]
            for row in recent_strategy_evals
            if row["symbol"] == symbol and row["recommendation"] in {"BLOCK", "AVOID"}
        )[:3]
        agent_rows = self._database.get_recent_agent_performance(limit=100)
        reliability = {row["agent_name"]: float(row["reliability_score"]) for row in agent_rows[:8]}
        outcome_rows = [row for row in matching if str(row.get("final_decision")) == "NO_TRADE"]
        missed_opportunities = sum(1 for row in outcome_rows if str(row.get("outcome_label") or "") in {"MISSED_OPPORTUNITY", "OVERFILTERED"})
        good_avoidances = sum(1 for row in outcome_rows if str(row.get("outcome_label") or "") in {"GOOD_AVOIDANCE", "BAD_TRADE_AVOIDED"})
        avg_edge = sum(float(row.get("expected_net_edge_pct") or 0.0) for row in matching) / sample_size if sample_size else 0.0
        if strategy_name in blocked:
            adjustment = min(adjustment, 0.0) - 0.08
        elif strategy_name in preferred:
            adjustment += 0.05
        if sample_size >= minimum_claim_sample and avg_edge > 0:
            adjustment += 0.04
        if missed_opportunities > good_avoidances and sample_size >= 10:
            adjustment += 0.02
        if good_avoidances > missed_opportunities and avg_edge <= 0:
            adjustment -= 0.02
        adjustment = max(-0.15, min(0.15, adjustment))
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
            reason=json.dumps(
                {
                    "sample_size": sample_size,
                    "market_state": market_state,
                    "paper_mode": paper_mode,
                    "avg_edge": round(avg_edge, 6),
                    "missed_opportunities": missed_opportunities,
                    "good_avoidances": good_avoidances,
                },
                ensure_ascii=True,
            ),
        )
