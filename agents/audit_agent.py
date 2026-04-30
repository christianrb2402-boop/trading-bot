from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(slots=True, frozen=True)
class AuditExplanation:
    summary: str
    risk_notes: tuple[str, ...]
    cost_notes: tuple[str, ...]
    committee_notes: tuple[str, ...]

    def as_dict(self) -> dict[str, str | tuple[str, ...]]:
        return {
            "summary": self.summary,
            "risk_notes": self.risk_notes,
            "cost_notes": self.cost_notes,
            "committee_notes": self.committee_notes,
        }


class AuditAgent:
    def explain_entry(
        self,
        *,
        final_decision: str,
        approved: bool,
        signal_reason: str,
        risk_reason: str,
        learning_reason: str,
        cost_snapshot: dict[str, object],
        committee_notes: Sequence[str],
    ) -> AuditExplanation:
        cost_notes = (
            f"fees_open={cost_snapshot.get('fees_open')}",
            f"fees_close={cost_snapshot.get('fees_close')}",
            f"slippage_cost={cost_snapshot.get('slippage_cost')}",
            f"spread_cost={cost_snapshot.get('spread_cost')}",
            f"funding_cost_estimate={cost_snapshot.get('funding_cost_estimate')}",
        )
        risk_notes = (risk_reason, learning_reason)
        summary = (
            f"{final_decision} approved for paper execution because {signal_reason}. "
            f"Risk/reward review: {risk_reason}. Learning memory: {learning_reason}."
            if approved
            else f"{final_decision} rejected. Signal view: {signal_reason}. Risk/reward review: {risk_reason}. Learning memory: {learning_reason}."
        )
        return AuditExplanation(
            summary=summary,
            risk_notes=tuple(note for note in risk_notes if note),
            cost_notes=cost_notes,
            committee_notes=tuple(committee_notes),
        )

    def explain_exit(
        self,
        *,
        reason_exit: str,
        net_pnl: float,
        gross_pnl: float,
        total_fees: float,
    ) -> str:
        return (
            f"Trade exited because {reason_exit}. Gross pnl was {round(gross_pnl, 6)}, "
            f"total estimated costs were {round(total_fees, 6)}, and net pnl finished at {round(net_pnl, 6)}."
        )
