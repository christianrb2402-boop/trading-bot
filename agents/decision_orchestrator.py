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
class TimeframeAlignment:
    timeframe_alignment: str
    dominant_trend_timeframe: str
    execution_timeframe: str
    context_timeframe_votes: tuple[str, ...]
    structural_bias: str
    alignment_score: float
    contradiction_score: float
    final_timeframe_reason: str
    supporting_timeframes: tuple[str, ...]
    rejecting_timeframes: tuple[str, ...]

    def as_dict(self) -> dict[str, str | float | tuple[str, ...]]:
        return {
            "timeframe_alignment": self.timeframe_alignment,
            "dominant_trend_timeframe": self.dominant_trend_timeframe,
            "execution_timeframe": self.execution_timeframe,
            "context_timeframe_votes": self.context_timeframe_votes,
            "structural_bias": self.structural_bias,
            "alignment_score": self.alignment_score,
            "contradiction_score": self.contradiction_score,
            "final_timeframe_reason": self.final_timeframe_reason,
            "supporting_timeframes": self.supporting_timeframes,
            "rejecting_timeframes": self.rejecting_timeframes,
        }


@dataclass(slots=True, frozen=True)
class OrchestratorDecision:
    final_decision: str
    decision_type: str
    final_confidence: float
    approved: bool
    explanation: str
    committee_notes: tuple[str, ...]
    timeframe_alignment: TimeframeAlignment

    def as_dict(self) -> dict[str, str | float | bool | tuple[str, ...] | dict[str, str | float | tuple[str, ...]]]:
        return {
            "final_decision": self.final_decision,
            "decision_type": self.decision_type,
            "final_confidence": self.final_confidence,
            "approved": self.approved,
            "explanation": self.explanation,
            "committee_notes": self.committee_notes,
            "timeframe_alignment": self.timeframe_alignment.as_dict(),
        }


class DecisionOrchestrator:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def assess_timeframes(
        self,
        *,
        symbol: str,
        direction: str,
        execution_timeframe: str,
        timeframe_contexts: dict[str, dict[str, object]],
    ) -> TimeframeAlignment:
        supporting: list[str] = []
        rejecting: list[str] = []
        context_votes: list[str] = []

        structural_frames = tuple(
            timeframe for timeframe in (*self._settings.context_timeframes, *self._settings.structural_timeframes)
            if timeframe in timeframe_contexts
        )
        dominant_trend_timeframe = execution_timeframe
        structural_bias = "MIXED"
        dominant_strength = -1.0
        contradiction_score = 0.0

        for timeframe, context in timeframe_contexts.items():
            trend = str(context.get("trend_direction", "SIDEWAYS"))
            market_regime = str(context.get("market_regime", "RANGING"))
            momentum_confirmed = bool(context.get("momentum_confirmed", False))
            context_votes.append(f"{timeframe}:{trend}:{market_regime}:{'MOMENTUM' if momentum_confirmed else 'WEAK'}")

            if trend == "SIDEWAYS":
                continue

            aligned = (direction == "LONG" and trend == "UP") or (direction == "SHORT" and trend == "DOWN")
            if aligned:
                supporting.append(timeframe)
            else:
                rejecting.append(timeframe)
                contradiction_score += 0.4 if timeframe in self._settings.context_timeframes else 0.25

            strength = float(context.get("context_score", 0.0))
            if strength > dominant_strength:
                dominant_strength = strength
                dominant_trend_timeframe = timeframe
                structural_bias = trend

        context_alignment = len(supporting) / max(len(supporting) + len(rejecting), 1)
        context_penalty = min(1.0, contradiction_score)
        alignment_score = max(0.0, min(1.0, context_alignment - (context_penalty * 0.35) + (0.1 if execution_timeframe in supporting else 0.0)))

        if not structural_frames:
            alignment_label = "TACTICAL_ONLY"
            reason = f"{symbol} has no higher-timeframe context available yet, so the setup is tactical only."
        elif execution_timeframe in self._settings.execution_timeframes and supporting and not rejecting:
            alignment_label = "FULL_ALIGNMENT"
            reason = f"{symbol} is aligned across execution and higher timeframes with structural bias {structural_bias}."
        elif execution_timeframe in self._settings.execution_timeframes and supporting and rejecting:
            alignment_label = "SCALP_ONLY"
            reason = f"{symbol} has tactical support on lower frames but higher frames are mixed or contradictory."
        elif rejecting:
            alignment_label = "CONTRADICTED"
            reason = f"{symbol} is contradicted by higher timeframes, especially {', '.join(rejecting[:3])}."
        else:
            alignment_label = "MIXED"
            reason = f"{symbol} does not have enough multi-timeframe agreement to be treated as a clean directional setup."

        return TimeframeAlignment(
            timeframe_alignment=alignment_label,
            dominant_trend_timeframe=dominant_trend_timeframe,
            execution_timeframe=execution_timeframe,
            context_timeframe_votes=tuple(context_votes),
            structural_bias=structural_bias,
            alignment_score=round(alignment_score, 6),
            contradiction_score=round(min(1.0, contradiction_score), 6),
            final_timeframe_reason=reason,
            supporting_timeframes=tuple(supporting),
            rejecting_timeframes=tuple(rejecting),
        )

    def decide(
        self,
        *,
        signal_tier: str,
        proposed_direction: str,
        votes: Sequence[AgentVote],
        current_open_positions: int,
        timeframe_alignment: TimeframeAlignment,
        symbol_selection_ok: bool,
    ) -> OrchestratorDecision:
        vote_map = {vote.agent_name: vote for vote in votes}
        notes = [f"{vote.agent_name}:{vote.vote}:{round(vote.confidence, 4)}" for vote in votes]

        if current_open_positions >= self._settings.max_open_positions:
            return self._reject(
                explanation="Rejected because max open positions limit is already reached.",
                notes=notes,
                timeframe_alignment=timeframe_alignment,
            )
        if not symbol_selection_ok:
            return self._reject(
                explanation="Rejected because symbol selection filters marked this setup as non-tradable today.",
                notes=notes,
                timeframe_alignment=timeframe_alignment,
            )

        if signal_tier == "WEAK" and not self._settings.allow_weak_signals:
            return self._reject("Rejected because weak signals are disabled.", notes, timeframe_alignment)
        if signal_tier == "MEDIUM" and not self._settings.allow_medium_signals:
            return self._reject("Rejected because medium signals are disabled.", notes, timeframe_alignment)
        if signal_tier == "STRONG" and not self._settings.allow_strong_signals:
            return self._reject("Rejected because strong signals are disabled.", notes, timeframe_alignment)

        for agent_name in ("MarketDataAgent", "RiskRewardAgent", "NetProfitabilityGate", "SymbolSelectionAgent"):
            vote = vote_map.get(agent_name)
            if vote and vote.vote == "REJECT":
                return self._reject(vote.reason, notes, timeframe_alignment)

        directional_votes = [vote for vote in votes if vote.vote in {"LONG", "SHORT"}]
        avg_confidence = sum(vote.confidence for vote in directional_votes) / len(directional_votes) if directional_votes else 0.0
        adjusted_confidence = avg_confidence + (timeframe_alignment.alignment_score * 0.2) - (timeframe_alignment.contradiction_score * 0.2)
        adjusted_confidence = max(0.0, min(1.0, adjusted_confidence))

        approved = proposed_direction in {"LONG", "SHORT"}
        explanation_parts = [
            f"base committee conviction was {round(avg_confidence, 4)}",
            f"timeframe alignment is {timeframe_alignment.timeframe_alignment}",
            timeframe_alignment.final_timeframe_reason,
        ]

        structural_opposes = (
            (proposed_direction == "LONG" and timeframe_alignment.structural_bias == "DOWN")
            or (proposed_direction == "SHORT" and timeframe_alignment.structural_bias == "UP")
        )

        aggressiveness = self._settings.aggressiveness_level
        decision_type = proposed_direction

        if aggressiveness == "CONSERVATIVE":
            approved = approved and adjusted_confidence >= 0.68 and timeframe_alignment.alignment_score >= 0.55 and timeframe_alignment.contradiction_score <= 0.25 and signal_tier in {"MEDIUM", "STRONG"}
        elif aggressiveness == "BALANCED":
            approved = approved and adjusted_confidence >= 0.5 and timeframe_alignment.contradiction_score <= 0.45
        elif aggressiveness == "AGGRESSIVE":
            approved = approved and adjusted_confidence >= 0.42 and timeframe_alignment.contradiction_score <= 0.55
        elif aggressiveness == "RESEARCH":
            approved = approved and adjusted_confidence >= 0.35 and timeframe_alignment.contradiction_score <= 0.7
            if approved:
                decision_type = "RESEARCH_TRADE"

        if structural_opposes and aggressiveness != "RESEARCH":
            adjusted_confidence = max(0.0, adjusted_confidence - 0.15)
            explanation_parts.append("structural bias opposes the trade direction")
            if timeframe_alignment.timeframe_alignment != "FULL_ALIGNMENT":
                approved = False

        if timeframe_alignment.timeframe_alignment == "SCALP_ONLY" and approved and aggressiveness in {"CONSERVATIVE", "BALANCED"}:
            adjusted_confidence = max(0.0, adjusted_confidence - 0.08)
            if aggressiveness == "CONSERVATIVE":
                approved = False
            else:
                decision_type = "SCALP_ONLY"

        if timeframe_alignment.timeframe_alignment == "CONTRADICTED":
            approved = False

        final_decision = proposed_direction if approved else "NO_TRADE"
        if not approved:
            explanation = "Committee rejected the setup. " + " ".join(explanation_parts)
            return OrchestratorDecision(
                final_decision=final_decision,
                decision_type="NO_TRADE",
                final_confidence=round(adjusted_confidence, 6),
                approved=False,
                explanation=explanation,
                committee_notes=tuple(notes),
                timeframe_alignment=timeframe_alignment,
            )

        explanation = (
            f"Committee approved {proposed_direction} as {decision_type} with adjusted confidence {round(adjusted_confidence, 4)}. "
            + " ".join(explanation_parts)
        )
        return OrchestratorDecision(
            final_decision=final_decision,
            decision_type=decision_type,
            final_confidence=round(adjusted_confidence, 6),
            approved=True,
            explanation=explanation,
            committee_notes=tuple(notes),
            timeframe_alignment=timeframe_alignment,
        )

    @staticmethod
    def _reject(explanation: str, notes: Sequence[str], timeframe_alignment: TimeframeAlignment) -> OrchestratorDecision:
        return OrchestratorDecision(
            final_decision="NO_TRADE",
            decision_type="NO_TRADE",
            final_confidence=0.0,
            approved=False,
            explanation=explanation,
            committee_notes=tuple(notes),
            timeframe_alignment=timeframe_alignment,
        )
