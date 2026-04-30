from __future__ import annotations

from dataclasses import dataclass

from agents.cost_model_agent import CostSnapshot
from config.settings import Settings


@dataclass(slots=True, frozen=True)
class RiskRewardAssessment:
    vote: str
    confidence: float
    reward_risk_ratio: float
    expected_reward_pct: float
    expected_risk_pct: float
    expected_net_reward_pct: float
    expected_net_risk_pct: float
    expected_net_reward_risk: float
    cost_drag_pct: float
    minimum_profitable_move_pct: float
    reason: str
    stop_loss_price: float
    take_profit_price: float

    def as_dict(self) -> dict[str, str | float]:
        return {
            "vote": self.vote,
            "confidence": self.confidence,
            "reward_risk_ratio": self.reward_risk_ratio,
            "expected_reward_pct": self.expected_reward_pct,
            "expected_risk_pct": self.expected_risk_pct,
            "expected_net_reward_pct": self.expected_net_reward_pct,
            "expected_net_risk_pct": self.expected_net_risk_pct,
            "expected_net_reward_risk": self.expected_net_reward_risk,
            "cost_drag_pct": self.cost_drag_pct,
            "minimum_profitable_move_pct": self.minimum_profitable_move_pct,
            "reason": self.reason,
            "stop_loss_price": self.stop_loss_price,
            "take_profit_price": self.take_profit_price,
        }


class RiskRewardAgent:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def evaluate(
        self,
        *,
        signal: dict[str, object],
        cost_snapshot: CostSnapshot,
    ) -> RiskRewardAssessment:
        direction = str(signal.get("signal_type", "NONE"))
        reward_risk_ratio = float(cost_snapshot.expected_gross_reward_pct) / max(float(cost_snapshot.expected_gross_risk_pct), 0.000001)
        expected_net_reward_risk = float(cost_snapshot.expected_net_reward_risk)
        expected_net_reward_pct = float(cost_snapshot.expected_net_reward_pct)
        expected_net_risk_pct = float(cost_snapshot.expected_net_risk_pct)
        minimum_profitable_move_pct = float(cost_snapshot.minimum_profitable_move_pct)
        cost_drag_pct = float(cost_snapshot.cost_drag_pct)

        approved = bool(
            direction in {"LONG", "SHORT"}
            and expected_net_reward_pct > self._settings.min_expected_net_edge_pct
            and expected_net_reward_risk >= self._settings.min_net_reward_risk_ratio
            and cost_drag_pct <= self._settings.max_cost_drag_pct
        )
        if approved:
            reason = (
                f"net reward/risk {round(expected_net_reward_risk, 4)} with expected net reward "
                f"{round(expected_net_reward_pct, 4)}% after estimated costs; cost drag {round(cost_drag_pct, 4)}"
            )
        else:
            reason = (
                f"rejected because net edge {round(expected_net_reward_pct, 4)}%, net reward/risk "
                f"{round(expected_net_reward_risk, 4)} and cost drag {round(cost_drag_pct, 4)} did not satisfy the filters"
            )

        return RiskRewardAssessment(
            vote=direction if approved else "REJECT",
            confidence=0.82 if approved else 0.22,
            reward_risk_ratio=round(reward_risk_ratio, 6),
            expected_reward_pct=round(float(cost_snapshot.expected_gross_reward_pct), 6),
            expected_risk_pct=round(float(cost_snapshot.expected_gross_risk_pct), 6),
            expected_net_reward_pct=round(expected_net_reward_pct, 6),
            expected_net_risk_pct=round(expected_net_risk_pct, 6),
            expected_net_reward_risk=round(expected_net_reward_risk, 6),
            cost_drag_pct=round(cost_drag_pct, 6),
            minimum_profitable_move_pct=round(minimum_profitable_move_pct, 6),
            reason=reason,
            stop_loss_price=float(cost_snapshot.stop_loss_price),
            take_profit_price=float(cost_snapshot.take_profit_price),
        )
