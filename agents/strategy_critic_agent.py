from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class StrategyCriticAssessment:
    critic_decision: str
    critic_score: float
    critic_reason: str
    penalties_applied: tuple[str, ...]
    rejection_reason: str | None
    raw_payload: dict[str, object]

    def as_dict(self) -> dict[str, object]:
        return {
            "critic_decision": self.critic_decision,
            "critic_score": self.critic_score,
            "critic_reason": self.critic_reason,
            "penalties_applied": self.penalties_applied,
            "rejection_reason": self.rejection_reason,
            "raw_payload": self.raw_payload,
        }


class StrategyCriticAgent:
    def critique(
        self,
        *,
        proposal: dict[str, object],
        total_cost_pct: float,
        expected_net_edge_pct: float,
        expected_net_reward_risk: float,
        timeframe_alignment: str,
        contradiction_score: float,
        market_state: str,
        is_stale: bool,
        gap_count: int,
        duplicate_setup: bool,
        loss_streak: int,
        data_quality_score: float,
    ) -> StrategyCriticAssessment:
        penalties: list[str] = []
        if timeframe_alignment == "CONTRADICTED":
            penalties.append("multi_timeframe_contradiction")
        if market_state in {"CHOPPY", "LOW_VOLATILITY", "UNKNOWN", "HIGH_VOLATILITY", "NEWSLIKE_SPIKE"}:
            penalties.append("hostile_market_state")
        if is_stale:
            penalties.append("stale_data")
        if gap_count >= 3:
            penalties.append("severe_gaps")
        if duplicate_setup:
            penalties.append("duplicate_setup")
        if loss_streak >= 5:
            penalties.append("loss_streak_critical")
        elif loss_streak >= 3:
            penalties.append("loss_streak_elevated")
        if data_quality_score < 0.55:
            penalties.append("poor_data_quality")
        if contradiction_score >= 0.75:
            penalties.append("critical_contradiction_score")
        elif contradiction_score >= 0.5:
            penalties.append("high_contradiction_score")

        if any(
            item in penalties
            for item in (
                "stale_data",
                "severe_gaps",
                "duplicate_setup",
                "loss_streak_critical",
                "critical_contradiction_score",
            )
        ) or data_quality_score < 0.4:
            return StrategyCriticAssessment(
                critic_decision="REJECT",
                critic_score=0.0,
                critic_reason="critic rejected the setup",
                penalties_applied=tuple(penalties),
                rejection_reason="; ".join(penalties),
                raw_payload={"proposal": proposal},
            )
        if penalties:
            return StrategyCriticAssessment(
                critic_decision="PENALIZE",
                critic_score=max(0.0, 1.0 - (0.12 * len(penalties))),
                critic_reason="critic penalized the setup",
                penalties_applied=tuple(penalties),
                rejection_reason=None,
                raw_payload={"proposal": proposal},
            )
        return StrategyCriticAssessment(
            critic_decision="APPROVE",
            critic_score=1.0,
            critic_reason="critic found no structural reason to block the setup",
            penalties_applied=(),
            rejection_reason=None,
            raw_payload={"proposal": proposal},
        )
