from __future__ import annotations

from dataclasses import dataclass

from config.settings import Settings


@dataclass(slots=True, frozen=True)
class CostSnapshot:
    market_type: str
    leverage_simulated: float
    notional_exposure: float
    fees_open: float
    fees_close: float
    total_fees: float
    slippage_cost: float
    spread_cost: float
    funding_rate_estimate: float
    funding_cost_estimate: float
    break_even_price: float
    minimum_required_move_to_profit: float

    def as_dict(self) -> dict[str, float | str]:
        return {
            "market_type": self.market_type,
            "leverage_simulated": self.leverage_simulated,
            "notional_exposure": self.notional_exposure,
            "fees_open": self.fees_open,
            "fees_close": self.fees_close,
            "total_fees": self.total_fees,
            "slippage_cost": self.slippage_cost,
            "spread_cost": self.spread_cost,
            "funding_rate_estimate": self.funding_rate_estimate,
            "funding_cost_estimate": self.funding_cost_estimate,
            "break_even_price": self.break_even_price,
            "minimum_required_move_to_profit": self.minimum_required_move_to_profit,
        }


class CostModelAgent:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def estimate(
        self,
        *,
        entry_price: float,
        stop_loss_price: float,
        direction: str,
        position_size_usd: float,
        leverage_simulated: float | None = None,
        market_type: str | None = None,
    ) -> CostSnapshot:
        leverage = min(
            max(leverage_simulated or self._settings.simulated_default_leverage, 1.0),
            max(self._settings.simulated_max_leverage, 1.0),
        )
        market = (market_type or self._settings.simulated_market_type).upper()
        notional = position_size_usd * leverage
        fees_open = notional * self._settings.simulated_fee_pct
        fees_close = notional * self._settings.simulated_fee_pct
        slippage_cost = notional * self._settings.simulated_slippage_pct * 2
        spread_cost = notional * self._settings.simulated_spread_pct
        funding_cost_estimate = notional * max(self._settings.simulated_funding_rate_estimate, 0.0) if market == "FUTURES_SIMULATED" else 0.0
        total_cost = fees_open + fees_close + slippage_cost + spread_cost + funding_cost_estimate
        quantity = notional / entry_price if entry_price else 0.0
        minimum_required_move = (total_cost / quantity) if quantity else 0.0
        if direction == "SHORT":
            break_even_price = entry_price - minimum_required_move
        else:
            break_even_price = entry_price + minimum_required_move

        return CostSnapshot(
            market_type=market,
            leverage_simulated=round(leverage, 6),
            notional_exposure=round(notional, 6),
            fees_open=round(fees_open, 6),
            fees_close=round(fees_close, 6),
            total_fees=round(fees_open + fees_close, 6),
            slippage_cost=round(slippage_cost, 6),
            spread_cost=round(spread_cost, 6),
            funding_rate_estimate=round(self._settings.simulated_funding_rate_estimate, 6),
            funding_cost_estimate=round(funding_cost_estimate, 6),
            break_even_price=round(break_even_price, 6),
            minimum_required_move_to_profit=round((minimum_required_move / entry_price) * 100, 6) if entry_price else 0.0,
        )
