from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from config.settings import Settings


@dataclass(slots=True, frozen=True)
class AgentVote:
    agent_name: str
    vote: str
    confidence: float
    reason: str
    risk_notes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, str | float | tuple[str, ...]]:
        return {
            "agent_name": self.agent_name,
            "vote": self.vote,
            "confidence": self.confidence,
            "reason": self.reason,
            "risk_notes": self.risk_notes,
        }


@dataclass(slots=True, frozen=True)
class OrchestratorDecision:
    final_decision: str
    final_confidence: float
    approved: bool
    explanation: str
    committee_notes: tuple[str, ...]

    def as_dict(self) -> dict[str, str | float | bool | tuple[str, ...]]:
        return {
            "final_decision": self.final_decision,
            "final_confidence": self.final_confidence,
            "approved": self.approved,
            "explanation": self.explanation,
            "committee_notes": self.committee_notes,
        }


class DecisionOrchestrator:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def decide(self, *, signal_tier: str, proposed_direction: str, votes: Sequence[AgentVote], current_open_positions: int) -> OrchestratorDecision:
        vote_map = {vote.agent_name: vote for vote in votes}
        notes = [f"{vote.agent_name}:{vote.vote}:{round(vote.confidence, 4)}" for vote in votes]
        if current_open_positions >= self._settings.max_open_positions:
            return OrchestratorDecision(
                final_decision="NO_TRADE",
                final_confidence=0.0,
                approved=False,
                explanation="Rejected because max open positions limit is already reached.",
                committee_notes=tuple(notes),
            )

        if signal_tier == "WEAK" and not self._settings.allow_weak_signals:
            return OrchestratorDecision("NO_TRADE", 0.0, False, "Rejected because weak signals are disabled.", tuple(notes))
        if signal_tier == "MEDIUM" and not self._settings.allow_medium_signals:
            return OrchestratorDecision("NO_TRADE", 0.0, False, "Rejected because medium signals are disabled.", tuple(notes))
        if signal_tier == "STRONG" and not self._settings.allow_strong_signals:
            return OrchestratorDecision("NO_TRADE", 0.0, False, "Rejected because strong signals are disabled.", tuple(notes))

        data_vote = vote_map.get("MarketDataAgent")
        risk_vote = vote_map.get("RiskRewardAgent")
        if data_vote and data_vote.vote == "REJECT":
            return OrchestratorDecision("NO_TRADE", 0.0, False, data_vote.reason, tuple(notes))
        if risk_vote and risk_vote.vote == "REJECT":
            return OrchestratorDecision("NO_TRADE", 0.0, False, risk_vote.reason, tuple(notes))

        directional_votes = [vote for vote in votes if vote.vote in {"LONG", "SHORT"}]
        avg_confidence = sum(vote.confidence for vote in directional_votes) / len(directional_votes) if directional_votes else 0.0
        approved = proposed_direction in {"LONG", "SHORT"} and avg_confidence >= 0.45
        final_decision = proposed_direction if approved else "NO_TRADE"
        explanation = (
            f"Committee approved {proposed_direction} with average confidence {round(avg_confidence, 4)}."
            if approved
            else f"Committee rejected the setup because aggregate conviction stayed too low at {round(avg_confidence, 4)}."
        )
        return OrchestratorDecision(
            final_decision=final_decision,
            final_confidence=round(avg_confidence, 6),
            approved=approved,
            explanation=explanation,
            committee_notes=tuple(notes),
        )
