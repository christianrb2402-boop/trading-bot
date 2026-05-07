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
    expected_value_pct: float
    probability_win: float
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
            "expected_value_pct": self.expected_value_pct,
            "probability_win": self.probability_win,
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
        risk_mode: str | None = None,
        paper_mode: str | None = None,
    ) -> NetProfitabilityAssessment:
        direction = str(signal.get("signal_type", "NONE"))
        effective_risk_mode = (risk_mode or str(signal.get("risk_mode", "")) or self._settings.aggressiveness_level).upper()
        effective_paper_mode = (paper_mode or str(signal.get("paper_mode", "")) or "PAPER_SELECTIVE").upper()
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
        probability_win = max(
            0.05,
            min(
                0.95,
                float(
                    signal.get(
                        "probability_win",
                        self._settings.paper_exploration_base_win_probability
                        if effective_paper_mode == "PAPER_EXPLORATION"
                        else self._settings.paper_selective_base_win_probability,
                    )
                ),
            ),
        )
        expected_value_pct = (probability_win * float(cost_snapshot.expected_net_reward_pct)) - (
            (1 - probability_win) * float(cost_snapshot.expected_net_risk_pct)
        )

        rejection_reasons: list[str] = []
        if effective_paper_mode == "OBSERVE_ONLY":
            rejection_reasons.append("paper mode OBSERVE_ONLY does not allow new paper trades")
        if effective_risk_mode in {"CAPITAL_PROTECTION", "DO_NOT_TRADE"}:
            rejection_reasons.append(f"risk mode {effective_risk_mode} blocks new entries")
        if effective_paper_mode == "PAPER_EXPLORATION":
            min_cost_coverage = self._settings.paper_exploration_min_cost_coverage
            min_rr = self._settings.paper_exploration_min_rr
            min_net_edge_pct = max(self._settings.min_expected_net_edge_pct * 0.5, 0.000001)
            volatility_headroom = 1.55
            rr_tolerance = 0.08
        elif effective_paper_mode == "PAPER_SELECTIVE":
            min_cost_coverage = self._settings.paper_selective_min_cost_coverage
            min_rr = self._settings.paper_selective_min_rr
            min_net_edge_pct = self._settings.min_expected_net_edge_pct
            volatility_headroom = 1.3
            rr_tolerance = 0.0
        elif effective_risk_mode == "CONSERVATIVE":
            min_cost_coverage = self._settings.min_cost_coverage_multiple_conservative
            min_rr = self._settings.min_net_reward_risk_ratio
            min_net_edge_pct = self._settings.min_expected_net_edge_pct
            volatility_headroom = 1.05
            rr_tolerance = 0.0
        elif effective_risk_mode in {"BALANCED", ""}:
            min_cost_coverage = self._settings.min_cost_coverage_multiple_balanced
            min_rr = self._settings.min_net_reward_risk_ratio
            min_net_edge_pct = self._settings.min_expected_net_edge_pct
            volatility_headroom = 1.15
            rr_tolerance = 0.0
        else:
            min_cost_coverage = self._settings.min_cost_coverage_multiple_aggressive
            min_rr = self._settings.min_net_reward_risk_ratio
            min_net_edge_pct = self._settings.min_expected_net_edge_pct
            volatility_headroom = 1.25
            rr_tolerance = 0.0
        if direction not in {"LONG", "SHORT"}:
            rejection_reasons.append("signal is not actionable")
        if expected_net_edge_value <= 0 or expected_net_edge_pct <= 0:
            rejection_reasons.append("expected net edge is not positive after estimated costs")
        if cost_coverage_multiple < min_cost_coverage:
            rejection_reasons.append(
                f"expected move only covers {round(cost_coverage_multiple, 4)}x estimated costs, below required {round(min_cost_coverage, 4)}x for {effective_paper_mode}/{effective_risk_mode}"
            )
        if (net_reward_risk + rr_tolerance) < min_rr:
            rejection_reasons.append(
                f"net reward/risk {round(net_reward_risk, 4)} is below minimum {min_rr}"
            )
        if expected_net_edge_pct < min_net_edge_pct:
            rejection_reasons.append(
                f"expected net edge {round(expected_net_edge_pct, 4)}% is below minimum {min_net_edge_pct}%"
            )
        if cost_drag_pct > self._settings.max_cost_drag_pct:
            rejection_reasons.append(
                f"cost drag {round(cost_drag_pct, 4)} exceeds maximum {self._settings.max_cost_drag_pct}"
            )
        if volatility_pct > 0 and minimum_required_move_pct > (volatility_pct * volatility_headroom):
            rejection_reasons.append(
                f"minimum profitable move {round(minimum_required_move_pct, 4)}% exceeds current volatility headroom {round(volatility_pct * volatility_headroom, 4)}%"
            )
        if effective_paper_mode == "PAPER_EXPLORATION" and len(rejection_reasons) > 1 and "signal is not actionable" in rejection_reasons:
            rejection_reasons = [reason for reason in rejection_reasons if reason != "signal is not actionable"]

        approved = not rejection_reasons
        if approved:
            reason = (
                f"net gate approved because expected move is {round(expected_move_pct, 4)}%, "
                f"estimated costs are {round(total_estimated_costs, 6)}, expected net edge is "
                f"{round(expected_net_edge_pct, 4)}%, expected value is {round(expected_value_pct, 4)}%, "
                f"and cost coverage is {round(cost_coverage_multiple, 4)}x."
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
            expected_value_pct=round(expected_value_pct, 6),
            probability_win=round(probability_win, 6),
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
