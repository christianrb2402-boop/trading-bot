from __future__ import annotations

from dataclasses import dataclass

from agents.cost_model_agent import CostSnapshot
from config.settings import Settings


@dataclass(slots=True, frozen=True)
class NetProfitabilityAssessment:
    vote: str
    confidence: float
    approved: bool
    total_estimated_costs: float
    break_even_price: float
    minimum_required_move_pct: float
    expected_move_pct: float
    expected_move_value: float
    expected_net_edge_pct: float
    expected_net_edge_value: float
    expected_net_reward_pct: float
    expected_net_risk_pct: float
    expected_net_reward_risk: float
    cost_coverage_multiple: float
    cost_drag_pct: float
    invalidation_price: float
    target_price: float
    close_condition: str
    reason: str
    rejection_reasons: tuple[str, ...]

    def as_dict(self) -> dict[str, str | float | bool | tuple[str, ...]]:
        return {
            "vote": self.vote,
            "confidence": self.confidence,
            "approved": self.approved,
            "total_estimated_costs": self.total_estimated_costs,
            "break_even_price": self.break_even_price,
            "minimum_required_move_pct": self.minimum_required_move_pct,
            "expected_move_pct": self.expected_move_pct,
            "expected_move_value": self.expected_move_value,
            "expected_net_edge_pct": self.expected_net_edge_pct,
            "expected_net_edge_value": self.expected_net_edge_value,
            "expected_net_reward_pct": self.expected_net_reward_pct,
            "expected_net_risk_pct": self.expected_net_risk_pct,
            "expected_net_reward_risk": self.expected_net_reward_risk,
            "cost_coverage_multiple": self.cost_coverage_multiple,
            "cost_drag_pct": self.cost_drag_pct,
            "invalidation_price": self.invalidation_price,
            "target_price": self.target_price,
            "close_condition": self.close_condition,
            "reason": self.reason,
            "rejection_reasons": self.rejection_reasons,
        }


class NetProfitabilityGate:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def evaluate(
        self,
        *,
        signal: dict[str, object],
        cost_snapshot: CostSnapshot,
    ) -> NetProfitabilityAssessment:
        direction = str(signal.get("signal_type", "NONE"))
        expected_move_pct = float(cost_snapshot.expected_gross_reward_pct)
        expected_move_value = float(cost_snapshot.notional_exposure) * (expected_move_pct / 100)
        total_estimated_costs = float(cost_snapshot.total_estimated_costs)
        expected_net_edge_value = expected_move_value - total_estimated_costs
        expected_net_edge_pct = float(cost_snapshot.expected_net_reward_pct)
        net_reward_risk = float(cost_snapshot.expected_net_reward_risk)
        cost_drag_pct = float(cost_snapshot.cost_drag_pct)
        minimum_required_move_pct = float(cost_snapshot.minimum_profitable_move_pct)
        cost_coverage_multiple = (
            expected_move_value / max(total_estimated_costs, 0.000001) if total_estimated_costs > 0 else float("inf")
        )
        volatility_pct = max(float(signal.get("volatility_pct", 0.0)), 0.0)

        rejection_reasons: list[str] = []
        if direction not in {"LONG", "SHORT"}:
            rejection_reasons.append("signal is not actionable")
        if expected_net_edge_value <= 0 or expected_net_edge_pct <= 0:
            rejection_reasons.append("expected net edge is not positive after estimated costs")
        if cost_coverage_multiple < self._settings.min_cost_coverage_multiple:
            rejection_reasons.append(
                f"expected move only covers {round(cost_coverage_multiple, 4)}x estimated costs"
            )
        if net_reward_risk < self._settings.min_net_reward_risk_ratio:
            rejection_reasons.append(
                f"net reward/risk {round(net_reward_risk, 4)} is below minimum {self._settings.min_net_reward_risk_ratio}"
            )
        if expected_net_edge_pct < self._settings.min_expected_net_edge_pct:
            rejection_reasons.append(
                f"expected net edge {round(expected_net_edge_pct, 4)}% is below minimum {self._settings.min_expected_net_edge_pct}%"
            )
        if cost_drag_pct > self._settings.max_cost_drag_pct:
            rejection_reasons.append(
                f"cost drag {round(cost_drag_pct, 4)} exceeds maximum {self._settings.max_cost_drag_pct}"
            )
        if volatility_pct > 0 and minimum_required_move_pct > volatility_pct:
            rejection_reasons.append(
                f"minimum profitable move {round(minimum_required_move_pct, 4)}% exceeds current volatility {round(volatility_pct, 4)}%"
            )

        approved = not rejection_reasons
        if approved:
            reason = (
                f"net gate approved because expected move is {round(expected_move_pct, 4)}%, "
                f"estimated costs are {round(total_estimated_costs, 6)}, expected net edge is "
                f"{round(expected_net_edge_pct, 4)}%, and cost coverage is {round(cost_coverage_multiple, 4)}x."
            )
            confidence = 0.9
            vote = direction
        else:
            reason = "net gate rejected because " + "; ".join(rejection_reasons)
            confidence = 0.18
            vote = "REJECT"

        return NetProfitabilityAssessment(
            vote=vote,
            confidence=confidence,
            approved=approved,
            total_estimated_costs=round(total_estimated_costs, 6),
            break_even_price=float(cost_snapshot.break_even_price),
            minimum_required_move_pct=round(minimum_required_move_pct, 6),
            expected_move_pct=round(expected_move_pct, 6),
            expected_move_value=round(expected_move_value, 6),
            expected_net_edge_pct=round(expected_net_edge_pct, 6),
            expected_net_edge_value=round(expected_net_edge_value, 6),
            expected_net_reward_pct=round(float(cost_snapshot.expected_net_reward_pct), 6),
            expected_net_risk_pct=round(float(cost_snapshot.expected_net_risk_pct), 6),
            expected_net_reward_risk=round(net_reward_risk, 6),
            cost_coverage_multiple=round(cost_coverage_multiple, 6) if cost_coverage_multiple != float("inf") else 999999.0,
            cost_drag_pct=round(cost_drag_pct, 6),
            invalidation_price=float(cost_snapshot.stop_loss_price),
            target_price=float(cost_snapshot.take_profit_price),
            close_condition=(
                f"close if price hits stop {round(float(cost_snapshot.stop_loss_price), 6)} or target "
                f"{round(float(cost_snapshot.take_profit_price), 6)}, or if the higher-timeframe context breaks down"
            ),
            reason=reason,
            rejection_reasons=tuple(rejection_reasons),
        )
