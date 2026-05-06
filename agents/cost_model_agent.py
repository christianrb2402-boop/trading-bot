from __future__ import annotations

from dataclasses import dataclass

from config.settings import Settings


@dataclass(slots=True, frozen=True)
class CostSnapshot:
    market_type: str
    leverage_simulated: float
    notional_exposure: float
    entry_fee_pct: float
    exit_fee_pct: float
    round_trip_fee_pct: float
    spread_pct: float
    slippage_entry_pct: float
    slippage_exit_pct: float
    fees_open: float
    fees_close: float
    total_fees: float
    slippage_cost: float
    spread_cost: float
    funding_rate_estimate: float
    funding_cost_estimate: float
    total_estimated_costs: float
    estimated_total_cost_pct: float
    break_even_price: float
    minimum_required_move_to_profit: float
    required_break_even_move_pct: float
    minimum_profitable_move_pct: float
    stop_loss_price: float
    take_profit_price: float
    expected_gross_reward_pct: float
    expected_gross_risk_pct: float
    expected_net_reward_pct: float
    expected_net_risk_pct: float
    expected_net_reward_risk: float
    net_reward_risk_ratio: float
    cost_drag_pct: float

    def as_dict(self) -> dict[str, float | str]:
        return {
            "market_type": self.market_type,
            "leverage_simulated": self.leverage_simulated,
            "notional_exposure": self.notional_exposure,
            "entry_fee_pct": self.entry_fee_pct,
            "exit_fee_pct": self.exit_fee_pct,
            "round_trip_fee_pct": self.round_trip_fee_pct,
            "spread_pct": self.spread_pct,
            "slippage_entry_pct": self.slippage_entry_pct,
            "slippage_exit_pct": self.slippage_exit_pct,
            "fees_open": self.fees_open,
            "fees_close": self.fees_close,
            "total_fees": self.total_fees,
            "slippage_cost": self.slippage_cost,
            "spread_cost": self.spread_cost,
            "funding_rate_estimate": self.funding_rate_estimate,
            "funding_cost_estimate": self.funding_cost_estimate,
            "total_estimated_costs": self.total_estimated_costs,
            "estimated_total_cost_pct": self.estimated_total_cost_pct,
            "break_even_price": self.break_even_price,
            "minimum_required_move_to_profit": self.minimum_required_move_to_profit,
            "required_break_even_move_pct": self.required_break_even_move_pct,
            "minimum_profitable_move_pct": self.minimum_profitable_move_pct,
            "stop_loss_price": self.stop_loss_price,
            "take_profit_price": self.take_profit_price,
            "expected_gross_reward_pct": self.expected_gross_reward_pct,
            "expected_gross_risk_pct": self.expected_gross_risk_pct,
            "expected_net_reward_pct": self.expected_net_reward_pct,
            "expected_net_risk_pct": self.expected_net_risk_pct,
            "expected_net_reward_risk": self.expected_net_reward_risk,
            "net_reward_risk_ratio": self.net_reward_risk_ratio,
            "cost_drag_pct": self.cost_drag_pct,
        }


class CostModelAgent:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def estimate(
        self,
        *,
        entry_price: float,
        direction: str,
        position_size_usd: float,
        volatility_pct: float = 0.0,
        leverage_simulated: float | None = None,
        market_type: str | None = None,
        stop_loss_price: float | None = None,
        take_profit_price: float | None = None,
    ) -> CostSnapshot:
        leverage = min(
            max(leverage_simulated or self._settings.simulated_default_leverage, 1.0),
            max(self._settings.simulated_max_leverage, 1.0),
        )
        market = (market_type or self._settings.simulated_market_type).upper()
        notional = position_size_usd * leverage
        entry_fee_rate = max(self._settings.simulated_taker_fee_pct, self._settings.simulated_fee_pct)
        exit_fee_rate = max(self._settings.simulated_taker_fee_pct, self._settings.simulated_fee_pct)
        fees_open = notional * entry_fee_rate
        fees_close = notional * exit_fee_rate
        slippage_cost = notional * self._settings.simulated_slippage_pct * 2
        spread_cost = notional * self._settings.simulated_spread_pct
        funding_cost_estimate = (
            notional * max(self._settings.simulated_funding_rate_estimate, 0.0)
            if market == "FUTURES_SIMULATED"
            else 0.0
        )
        total_cost = fees_open + fees_close + slippage_cost + spread_cost + funding_cost_estimate
        quantity = notional / entry_price if entry_price else 0.0

        stop_pct = max(self._settings.simulated_stop_loss_pct * 100, volatility_pct or 0.0, 0.05)
        reward_pct = max(
            self._settings.simulated_take_profit_pct * 100,
            stop_pct * max(self._settings.min_reward_risk_ratio, 1.0),
        )

        if stop_loss_price is None:
            stop_loss_price = entry_price * (1 + (stop_pct / 100)) if direction == "SHORT" else entry_price * (1 - (stop_pct / 100))
        else:
            stop_pct = abs(((stop_loss_price - entry_price) / entry_price) * 100)

        if take_profit_price is None:
            take_profit_price = entry_price * (1 - (reward_pct / 100)) if direction == "SHORT" else entry_price * (1 + (reward_pct / 100))
        else:
            reward_pct = abs(((take_profit_price - entry_price) / entry_price) * 100)

        minimum_required_move = (total_cost / quantity) if quantity else 0.0
        minimum_profitable_move_pct = (minimum_required_move / entry_price) * 100 if entry_price else 0.0
        minimum_take_profit_pct = minimum_profitable_move_pct * max(self._settings.paper_exploration_min_cost_coverage, 1.0)
        if reward_pct < minimum_take_profit_pct:
            reward_pct = minimum_take_profit_pct
            take_profit_price = entry_price * (1 - (reward_pct / 100)) if direction == "SHORT" else entry_price * (1 + (reward_pct / 100))
        break_even_price = entry_price - minimum_required_move if direction == "SHORT" else entry_price + minimum_required_move

        expected_net_reward_pct = max(reward_pct - minimum_profitable_move_pct, 0.0)
        expected_net_risk_pct = stop_pct + minimum_profitable_move_pct
        expected_net_reward_risk = expected_net_reward_pct / max(expected_net_risk_pct, 0.000001)
        cost_drag_pct = (minimum_profitable_move_pct / max(reward_pct, 0.000001)) if reward_pct else 1.0
        estimated_total_cost_pct = (
            (entry_fee_rate + exit_fee_rate + (self._settings.simulated_slippage_pct * 2) + self._settings.simulated_spread_pct + max(self._settings.simulated_funding_rate_estimate, 0.0))
            * 100
        )

        return CostSnapshot(
            market_type=market,
            leverage_simulated=round(leverage, 6),
            notional_exposure=round(notional, 6),
            entry_fee_pct=round(entry_fee_rate * 100, 6),
            exit_fee_pct=round(exit_fee_rate * 100, 6),
            round_trip_fee_pct=round((entry_fee_rate + exit_fee_rate) * 100, 6),
            spread_pct=round(self._settings.simulated_spread_pct * 100, 6),
            slippage_entry_pct=round(self._settings.simulated_slippage_pct * 100, 6),
            slippage_exit_pct=round(self._settings.simulated_slippage_pct * 100, 6),
            fees_open=round(fees_open, 6),
            fees_close=round(fees_close, 6),
            total_fees=round(fees_open + fees_close, 6),
            slippage_cost=round(slippage_cost, 6),
            spread_cost=round(spread_cost, 6),
            funding_rate_estimate=round(self._settings.simulated_funding_rate_estimate, 6),
            funding_cost_estimate=round(funding_cost_estimate, 6),
            total_estimated_costs=round(total_cost, 6),
            estimated_total_cost_pct=round(estimated_total_cost_pct, 6),
            break_even_price=round(break_even_price, 6),
            minimum_required_move_to_profit=round(minimum_profitable_move_pct, 6),
            required_break_even_move_pct=round(minimum_profitable_move_pct, 6),
            minimum_profitable_move_pct=round(minimum_profitable_move_pct, 6),
            stop_loss_price=round(stop_loss_price, 6),
            take_profit_price=round(take_profit_price, 6),
            expected_gross_reward_pct=round(reward_pct, 6),
            expected_gross_risk_pct=round(stop_pct, 6),
            expected_net_reward_pct=round(expected_net_reward_pct, 6),
            expected_net_risk_pct=round(expected_net_risk_pct, 6),
            expected_net_reward_risk=round(expected_net_reward_risk, 6),
            net_reward_risk_ratio=round(expected_net_reward_risk, 6),
            cost_drag_pct=round(cost_drag_pct, 6),
        )
