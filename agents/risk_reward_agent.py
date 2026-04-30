from __future__ import annotations

from dataclasses import dataclass

from config.settings import Settings


@dataclass(slots=True, frozen=True)
class RiskRewardAssessment:
    vote: str
    confidence: float
    reward_risk_ratio: float
    expected_reward_pct: float
    expected_risk_pct: float
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
        price: float,
        volatility_pct: float,
        estimated_cost_pct: float,
    ) -> RiskRewardAssessment:
        direction = str(signal.get("signal_type", "NONE"))
        base_stop_pct = max(self._settings.simulated_stop_loss_pct * 100, max(volatility_pct, 0.05))
        base_reward_pct = max(self._settings.simulated_take_profit_pct * 100, base_stop_pct * self._settings.min_reward_risk_ratio)
        reward_risk_ratio = base_reward_pct / max(base_stop_pct, 0.000001)
        cost_adjusted_reward_pct = max(base_reward_pct - estimated_cost_pct, 0.0)

        if direction == "SHORT":
            stop_loss_price = price * (1 + (base_stop_pct / 100))
            take_profit_price = price * (1 - (base_reward_pct / 100))
        else:
            stop_loss_price = price * (1 - (base_stop_pct / 100))
            take_profit_price = price * (1 + (base_reward_pct / 100))

        approved = direction in {"LONG", "SHORT"} and reward_risk_ratio >= self._settings.min_reward_risk_ratio and cost_adjusted_reward_pct > base_stop_pct * 0.25
        reason = (
            f"reward/risk {round(reward_risk_ratio, 4)} with expected reward {round(cost_adjusted_reward_pct, 4)}% after costs"
            if approved
            else f"reward/risk {round(reward_risk_ratio, 4)} was not attractive enough after estimated costs"
        )
        return RiskRewardAssessment(
            vote=direction if approved else "REJECT",
            confidence=0.8 if approved else 0.25,
            reward_risk_ratio=round(reward_risk_ratio, 6),
            expected_reward_pct=round(cost_adjusted_reward_pct, 6),
            expected_risk_pct=round(base_stop_pct, 6),
            reason=reason,
            stop_loss_price=round(stop_loss_price, 6),
            take_profit_price=round(take_profit_price, 6),
        )
