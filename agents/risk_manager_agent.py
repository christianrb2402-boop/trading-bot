from __future__ import annotations

from dataclasses import dataclass

from config.settings import Settings
from core.ledger_reconciler import LedgerConsistencyReport


@dataclass(slots=True, frozen=True)
class RiskManagerAssessment:
    risk_mode: str
    position_size_pct: float
    max_open_positions: int
    max_symbol_exposure: float
    max_strategy_exposure: float
    max_timeframe_exposure: float
    max_daily_drawdown_pct: float
    max_consecutive_losses: int
    current_drawdown: float
    loss_streak: int
    recommended_action: str
    reason: str

    def as_dict(self) -> dict[str, object]:
        return {
            "risk_mode": self.risk_mode,
            "position_size_pct": self.position_size_pct,
            "max_open_positions": self.max_open_positions,
            "max_symbol_exposure": self.max_symbol_exposure,
            "max_strategy_exposure": self.max_strategy_exposure,
            "max_timeframe_exposure": self.max_timeframe_exposure,
            "max_daily_drawdown_pct": self.max_daily_drawdown_pct,
            "max_consecutive_losses": self.max_consecutive_losses,
            "current_drawdown": self.current_drawdown,
            "loss_streak": self.loss_streak,
            "recommended_action": self.recommended_action,
            "reason": self.reason,
        }


class RiskManagerAgent:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def assess(
        self,
        *,
        ledger_report: LedgerConsistencyReport,
        market_risk_mode: str,
        current_drawdown_pct: float,
        loss_streak: int,
        open_positions: int,
        stale_data: bool,
    ) -> RiskManagerAssessment:
        risk_mode = market_risk_mode
        recommended_action = "ALLOW"
        if ledger_report.result != "OK":
            risk_mode = "CAPITAL_PROTECTION"
            recommended_action = "BLOCK"
        if stale_data:
            risk_mode = "DO_NOT_TRADE"
            recommended_action = "BLOCK"
        if loss_streak >= 5:
            risk_mode = "CAPITAL_PROTECTION"
            recommended_action = "BLOCK"
        elif loss_streak >= 3 and risk_mode not in {"DO_NOT_TRADE", "CAPITAL_PROTECTION"}:
            risk_mode = "CONSERVATIVE"
        if current_drawdown_pct <= -(self._settings.max_daily_drawdown_pct * 100):
            risk_mode = "CAPITAL_PROTECTION"
            recommended_action = "BLOCK"
        if open_positions >= self._settings.max_open_positions:
            recommended_action = "BLOCK"
        size_pct = self._settings.max_position_size_pct
        if risk_mode == "CONSERVATIVE":
            size_pct *= 0.6
        elif risk_mode == "CAPITAL_PROTECTION":
            size_pct *= 0.25
        elif risk_mode == "DO_NOT_TRADE":
            size_pct = 0.0
        elif risk_mode == "AGGRESSIVE":
            size_pct *= 1.0
        else:
            size_pct *= 0.8
        reason = (
            f"risk mode {risk_mode}, drawdown {round(current_drawdown_pct, 4)}%, "
            f"loss streak {loss_streak}, ledger {ledger_report.result}, open positions {open_positions}"
        )
        return RiskManagerAssessment(
            risk_mode=risk_mode,
            position_size_pct=round(size_pct, 6),
            max_open_positions=self._settings.max_open_positions,
            max_symbol_exposure=self._settings.max_symbol_exposure_pct,
            max_strategy_exposure=self._settings.max_strategy_exposure_pct,
            max_timeframe_exposure=self._settings.max_position_size_pct,
            max_daily_drawdown_pct=self._settings.max_daily_drawdown_pct,
            max_consecutive_losses=self._settings.max_consecutive_losses,
            current_drawdown=round(current_drawdown_pct, 6),
            loss_streak=loss_streak,
            recommended_action=recommended_action,
            reason=reason,
        )

