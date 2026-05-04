from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import json
import logging

from config.settings import Settings
from core.database import Database, SimulatedTradeRecord, StoredCandle


logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class SimulatedTradeStats:
    symbol: str
    total_trades: int
    open_trades: int
    closed_trades: int
    winrate: float
    average_pnl: float
    average_pnl_pct: float
    cumulative_pnl: float
    drawdown: float


@dataclass(slots=True, frozen=True)
class SimulatedTradeCycleResult:
    opened_trade_id: int | None
    closed_trade_id: int | None
    active_trade_id: int | None
    opened: bool
    closed: bool


class SimulatedTradeTracker:
    def __init__(self, database: Database, settings: Settings) -> None:
        self._database = database
        self._position_size_usd = settings.simulated_position_size_usd
        self._fee_pct = settings.simulated_fee_pct
        self._slippage_pct = settings.simulated_slippage_pct
        self._spread_pct = settings.simulated_spread_pct
        self._stop_loss_pct = settings.simulated_stop_loss_pct
        self._take_profit_pct = settings.simulated_take_profit_pct
        self._max_hold_candles = settings.simulated_max_hold_candles
        self._risk_reward_ratio = max(
            settings.min_reward_risk_ratio,
            settings.simulated_take_profit_pct / max(settings.simulated_stop_loss_pct, 0.000001),
        )
        self._market_type = settings.simulated_market_type
        self._default_leverage = min(
            max(settings.simulated_default_leverage, 1.0),
            max(settings.simulated_max_leverage, 1.0),
        )
        self._funding_rate_estimate = max(settings.simulated_funding_rate_estimate, 0.0)

    def process_cycle(
        self,
        *,
        symbol: str,
        timeframe: str,
        signal: dict[str, str | float | bool],
        latest_candle: StoredCandle,
        signal_id: int | None,
        current_time: str | None = None,
        enable_wall_clock_expiry: bool = True,
    ) -> SimulatedTradeCycleResult:
        closed_trade_id = self._update_open_trade(
            symbol=symbol,
            timeframe=timeframe,
            latest_candle=latest_candle,
            current_time=current_time,
            enable_wall_clock_expiry=enable_wall_clock_expiry,
        )
        open_trade = self._database.get_open_simulated_trade(symbol, timeframe)

        signal_type = str(signal["signal_type"])
        opened_trade_id: int | None = None
        if signal_type in {"LONG", "SHORT"} and open_trade is None and not self._is_duplicate_setup(
            symbol=symbol,
            timeframe=timeframe,
            direction=signal_type,
            entry_time=latest_candle.close_time,
            setup_signature=str(signal.get("setup_signature", "")),
        ):
            opened_trade_id = self._open_trade(
                symbol=symbol,
                timeframe=timeframe,
                latest_candle=latest_candle,
                signal=signal,
                signal_id=signal_id,
            )
            open_trade = self._database.get_open_simulated_trade(symbol, timeframe)
        elif signal_type in {"LONG", "SHORT"} and open_trade is not None:
            logger.info(
                "Simulated trade rejected",
                extra={
                    "event": "trade_simulation_rejected",
                    "context": {
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "reason": "existing_open_trade",
                        "active_trade_id": open_trade.id,
                        "incoming_signal": signal_type,
                    },
                },
            )
        elif signal_type in {"LONG", "SHORT"}:
            logger.info(
                "Simulated trade rejected",
                extra={
                    "event": "trade_simulation_rejected",
                    "context": {
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "reason": "duplicate_setup",
                        "incoming_signal": signal_type,
                        "setup_signature": str(signal.get("setup_signature", "")),
                    },
                },
            )
        elif signal_type != "NONE":
            logger.info(
                "Simulated trade rejected",
                extra={
                    "event": "trade_simulation_rejected",
                    "context": {
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "reason": f"non_actionable_signal:{signal['signal_type']}",
                    },
                },
            )

        active_trade_id = open_trade.id if open_trade else None
        return SimulatedTradeCycleResult(
            opened_trade_id=opened_trade_id,
            closed_trade_id=closed_trade_id,
            active_trade_id=active_trade_id,
            opened=opened_trade_id is not None,
            closed=closed_trade_id is not None,
        )

    def finalize_open_trade(
        self,
        *,
        symbol: str,
        timeframe: str,
        latest_candle: StoredCandle,
        reason_exit: str = "Closed at end of backtest window",
    ) -> int | None:
        trade = self._database.get_open_simulated_trade(symbol, timeframe)
        if trade is None:
            return None
        exit_price = self._exit_fill_price(direction=trade.direction, mark_price=latest_candle.close)
        self._close_trade(
            trade=trade,
            exit_price=exit_price,
            exit_time=latest_candle.close_time,
            status="EXPIRED",
            reason_exit=reason_exit,
            exit_context={"close_reason": "window_end"},
        )
        return trade.id

    def force_close_trade(
        self,
        *,
        symbol: str,
        timeframe: str,
        latest_candle: StoredCandle,
        reason_exit: str,
        status: str = "CLOSED",
        exit_context: dict[str, object] | None = None,
    ) -> int | None:
        trade = self._database.get_open_simulated_trade(symbol, timeframe)
        if trade is None:
            return None
        exit_price = self._exit_fill_price(direction=trade.direction, mark_price=latest_candle.close)
        self._close_trade(
            trade=trade,
            exit_price=exit_price,
            exit_time=latest_candle.close_time,
            status=status,
            reason_exit=reason_exit,
            exit_context=exit_context,
        )
        return trade.id

    def build_stats(self, symbol: str) -> SimulatedTradeStats:
        closed_trades = self._database.get_closed_simulated_trades(symbol)
        open_trades = [trade for trade in self._database.get_open_simulated_trades() if trade.symbol == symbol]
        if not closed_trades:
            return SimulatedTradeStats(
                symbol=symbol,
                total_trades=len(open_trades),
                open_trades=len(open_trades),
                closed_trades=0,
                winrate=0.0,
                average_pnl=0.0,
                average_pnl_pct=0.0,
                cumulative_pnl=0.0,
                drawdown=0.0,
            )

        wins = sum(
            1
            for trade in closed_trades
            if (
                trade.final_net_pnl_after_all_costs
                if trade.final_net_pnl_after_all_costs is not None
                else (trade.net_pnl if trade.net_pnl is not None else (trade.pnl or 0.0))
            ) > 0
        )
        cumulative = 0.0
        peak = 0.0
        max_drawdown = 0.0
        for trade in closed_trades:
            cumulative += (
                trade.final_net_pnl_after_all_costs
                if trade.final_net_pnl_after_all_costs is not None
                else (trade.net_pnl if trade.net_pnl is not None else (trade.pnl or 0.0))
            )
            peak = max(peak, cumulative)
            max_drawdown = min(max_drawdown, cumulative - peak)
        average_pnl = sum(
            (
                trade.final_net_pnl_after_all_costs
                if trade.final_net_pnl_after_all_costs is not None
                else (trade.net_pnl if trade.net_pnl is not None else (trade.pnl or 0.0))
            )
            for trade in closed_trades
        ) / len(closed_trades)
        average_pnl_pct = sum(
            (
                trade.final_net_pnl_after_all_costs_pct
                if trade.final_net_pnl_after_all_costs_pct is not None
                else (trade.net_pnl_pct if trade.net_pnl_pct is not None else (trade.pnl_pct or 0.0))
            )
            for trade in closed_trades
        ) / len(closed_trades)
        return SimulatedTradeStats(
            symbol=symbol,
            total_trades=len(open_trades) + len(closed_trades),
            open_trades=len(open_trades),
            closed_trades=len(closed_trades),
            winrate=round((wins / len(closed_trades)) * 100, 2),
            average_pnl=round(average_pnl, 6),
            average_pnl_pct=round(average_pnl_pct, 6),
            cumulative_pnl=round(cumulative, 6),
            drawdown=round(max_drawdown, 6),
        )

    def _open_trade(
        self,
        *,
        symbol: str,
        timeframe: str,
        latest_candle: StoredCandle,
        signal: dict[str, str | float | bool],
        signal_id: int | None,
    ) -> int:
        direction = str(signal.get("signal_type", "LONG"))
        entry_price = self._entry_fill_price(direction=direction, mark_price=latest_candle.close)
        risk_reward_snapshot = signal.get("risk_reward_snapshot", {})
        stop_loss = float(risk_reward_snapshot.get("stop_loss_price", 0.0) or 0.0)
        take_profit = float(risk_reward_snapshot.get("take_profit_price", 0.0) or 0.0)
        if stop_loss <= 0 or take_profit <= 0:
            signal_volatility_pct = max(float(signal.get("volatility_pct", 0.0)), 0.0) / 100
            stop_loss_pct = max(self._stop_loss_pct, signal_volatility_pct)
            take_profit_pct = max(self._take_profit_pct, stop_loss_pct * self._risk_reward_ratio)
            if direction == "SHORT":
                stop_loss = entry_price * (1 + stop_loss_pct)
                take_profit = entry_price * (1 - take_profit_pct)
            else:
                stop_loss = entry_price * (1 - stop_loss_pct)
                take_profit = entry_price * (1 + take_profit_pct)

        leverage_simulated = float(signal.get("leverage_simulated", self._default_leverage))
        position_size_usd = max(float(signal.get("position_size_usd", self._position_size_usd) or self._position_size_usd), 1.0)
        notional_exposure = position_size_usd * leverage_simulated
        quantity = notional_exposure / entry_price if entry_price else 0.0
        cost_snapshot = signal.get("cost_snapshot", {})
        fees_open = float(cost_snapshot.get("fees_open", notional_exposure * self._fee_pct))
        slippage_cost = float(cost_snapshot.get("slippage_cost", notional_exposure * self._slippage_pct))
        spread_cost = float(cost_snapshot.get("spread_cost", notional_exposure * self._spread_pct))
        funding_cost_estimate = float(
            cost_snapshot.get(
                "funding_cost_estimate",
                notional_exposure * self._funding_rate_estimate if self._market_type == "FUTURES_SIMULATED" else 0.0,
            )
        )
        minimum_required_move = ((fees_open * 2) + slippage_cost + spread_cost + funding_cost_estimate) / quantity if quantity else 0.0
        break_even_price = entry_price - minimum_required_move if direction == "SHORT" else entry_price + minimum_required_move
        liquidation_price_estimate = (
            entry_price * (1 + (0.9 / max(leverage_simulated, 1.0)))
            if direction == "SHORT"
            else entry_price * (1 - (0.9 / max(leverage_simulated, 1.0)))
        )
        cost_snapshot = {
            "fees_open": round(fees_open, 6),
            "estimated_fees_close": round(fees_open, 6),
            "slippage_cost": round(slippage_cost, 6),
            "spread_cost": round(spread_cost, 6),
            "funding_cost_estimate": round(funding_cost_estimate, 6),
            "break_even_price": round(break_even_price, 6),
            "minimum_required_move_to_profit": round((minimum_required_move / entry_price) * 100, 6) if entry_price else 0.0,
        }

        trade_id = self._database.insert_simulated_trade(
            symbol=symbol,
            timeframe=timeframe,
            direction=direction,
            status="OPEN",
            decision_type=str(signal.get("decision_type", signal["signal_type"])),
            entry_time=latest_candle.close_time,
            entry_price=round(entry_price, 6),
            stop_loss=round(stop_loss, 6),
            take_profit=round(take_profit, 6),
            signal_strength=float(signal.get("signal_strength", signal.get("k_value", 0.0))),
            fee_pct=self._fee_pct,
            fees_paid=round(fees_open, 6),
            slippage_pct=self._slippage_pct,
            signal_id=signal_id,
            entry_trend=str(signal.get("trend_direction")),
            entry_volatility_bucket=str(signal.get("volatility_regime", signal.get("volatility_bucket"))),
            entry_momentum_bucket=str(signal.get("momentum_bucket")),
            entry_volume_regime=str(signal.get("volume_regime")),
            entry_market_regime=str(signal.get("market_regime")),
            setup_signature=str(signal.get("setup_signature")),
            reason_entry=str(signal["explanation"]),
            provider_used=str(signal.get("provider_used", latest_candle.provider)),
            market_type=self._market_type,
            leverage_simulated=leverage_simulated,
            margin_used=position_size_usd,
            liquidation_price_estimate=round(liquidation_price_estimate, 6),
            funding_rate_estimate=self._funding_rate_estimate,
            funding_cost_estimate=round(funding_cost_estimate, 6),
            notional_exposure=round(notional_exposure, 6),
            fees_open=round(fees_open, 6),
            slippage_cost=round(slippage_cost, 6),
            spread_cost=round(spread_cost, 6),
            break_even_price=round(break_even_price, 6),
            minimum_required_move_to_profit=cost_snapshot["minimum_required_move_to_profit"],
            entry_context=json.dumps(
                {
                    "trend_direction": signal.get("trend_direction"),
                    "volatility_regime": signal.get("volatility_regime"),
                    "momentum_strength": signal.get("momentum_strength"),
                    "volume_regime": signal.get("volume_regime"),
                    "market_regime": signal.get("market_regime"),
                    "provider_used": signal.get("provider_used", latest_candle.provider),
                },
                ensure_ascii=True,
            ),
            agent_votes=json.dumps(signal.get("agent_votes", []), ensure_ascii=True),
            risk_reward_snapshot=json.dumps(signal.get("risk_reward_snapshot", {}), ensure_ascii=True),
            cost_snapshot=json.dumps(cost_snapshot, ensure_ascii=True),
            paper_mode=str(signal.get("paper_mode", "OBSERVE_ONLY")),
            exploratory_trade=str(signal.get("paper_mode", "OBSERVE_ONLY")) == "PAPER_EXPLORATION",
        )
        logger.info(
            "Simulated trade opened",
            extra={
                "event": "trade_simulation_open",
                "context": {
                    "trade_id": trade_id,
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "direction": direction,
                    "entry_price": round(entry_price, 6),
                    "entry_time": latest_candle.close_time,
                    "stop_loss": round(stop_loss, 6),
                    "take_profit": round(take_profit, 6),
                    "provider_used": str(signal.get("provider_used", latest_candle.provider)),
                    "market_type": self._market_type,
                    "leverage_simulated": leverage_simulated,
                    "signal_id": signal_id,
                },
            },
        )
        return trade_id

    def _is_duplicate_setup(
        self,
        *,
        symbol: str,
        timeframe: str,
        direction: str,
        entry_time: str,
        setup_signature: str,
    ) -> bool:
        with self._database.connection() as conn:
            row = conn.execute(
                """
                SELECT id
                FROM simulated_trades
                WHERE symbol = ?
                  AND COALESCE(timeframe, '1m') = ?
                  AND direction = ?
                  AND COALESCE(entry_time, timestamp_entry) = ?
                  AND COALESCE(setup_signature, '') = ?
                LIMIT 1
                """,
                (symbol, timeframe, direction, entry_time, setup_signature),
            ).fetchone()
        return row is not None

    def _update_open_trade(
        self,
        *,
        symbol: str,
        timeframe: str,
        latest_candle: StoredCandle,
        current_time: str | None,
        enable_wall_clock_expiry: bool,
    ) -> int | None:
        trade = self._database.get_open_simulated_trade(symbol, timeframe)
        if trade is None:
            return None

        trade = self._ensure_trade_protection(trade=trade)
        trade = self._maybe_trail_to_breakeven(trade=trade, latest_candle=latest_candle)

        if trade.direction == "SHORT":
            stop_loss_hit = trade.stop_loss is not None and latest_candle.high >= trade.stop_loss
            take_profit_hit = trade.take_profit is not None and latest_candle.low <= trade.take_profit
        else:
            stop_loss_hit = trade.stop_loss is not None and latest_candle.low <= trade.stop_loss
            take_profit_hit = trade.take_profit is not None and latest_candle.high >= trade.take_profit

        if stop_loss_hit:
            self._close_trade(
                trade=trade,
                exit_price=self._exit_fill_price(direction=trade.direction, mark_price=trade.stop_loss or latest_candle.close),
                exit_time=latest_candle.close_time,
                status="STOP_LOSS",
                reason_exit="Closed at stop loss level",
                exit_context={"close_reason": "stop_loss"},
            )
            return trade.id

        if take_profit_hit:
            self._close_trade(
                trade=trade,
                exit_price=self._exit_fill_price(direction=trade.direction, mark_price=trade.take_profit or latest_candle.close),
                exit_time=latest_candle.close_time,
                status="TAKE_PROFIT",
                reason_exit="Closed at take profit level",
                exit_context={"close_reason": "take_profit"},
            )
            return trade.id

        held_candles = self._database.count_candles_between(
            symbol=symbol,
            timeframe=timeframe,
            start_time_exclusive=trade.entry_time,
            end_time_inclusive=latest_candle.close_time,
        )
        if self._max_hold_candles > 0 and held_candles >= self._max_hold_candles:
            self._close_trade(
                trade=trade,
                exit_price=self._exit_fill_price(direction=trade.direction, mark_price=latest_candle.close),
                exit_time=latest_candle.close_time,
                status="EXPIRED",
                reason_exit=f"Closed after reaching max hold of {self._max_hold_candles} candles",
                exit_context={"close_reason": "max_hold_candles"},
            )
            return trade.id

        if enable_wall_clock_expiry:
            entry_dt = datetime.fromisoformat(trade.entry_time)
            now_dt = datetime.fromisoformat(current_time) if current_time else datetime.now(timezone.utc)
            max_hold_seconds = self._max_hold_candles * 60
            if self._max_hold_candles > 0 and int((now_dt - entry_dt).total_seconds()) >= max_hold_seconds:
                self._close_trade(
                    trade=trade,
                    exit_price=self._exit_fill_price(direction=trade.direction, mark_price=latest_candle.close),
                    exit_time=now_dt.isoformat(),
                    status="EXPIRED",
                    reason_exit="Closed after max hold time elapsed without fresher candles",
                    exit_context={"close_reason": "wall_clock_expiry"},
                )
                return trade.id
        return None

    def _close_trade(
        self,
        *,
        trade: SimulatedTradeRecord,
        exit_price: float,
        exit_time: str,
        status: str,
        reason_exit: str,
        exit_context: dict[str, object] | None = None,
    ) -> None:
        notional_exposure = trade.notional_exposure or (self._position_size_usd * (trade.leverage_simulated or 1.0))
        quantity = notional_exposure / trade.entry_price if trade.entry_price else 0.0
        exit_notional = quantity * exit_price
        fees_close = exit_notional * trade.fee_pct
        total_fees = (trade.fees_open or trade.fees_paid or 0.0) + fees_close
        if trade.direction == "SHORT":
            gross_pnl = (trade.entry_price - exit_price) * quantity
        else:
            gross_pnl = (exit_price - trade.entry_price) * quantity
        net_pnl_before_funding = gross_pnl - total_fees - (trade.slippage_cost or 0.0) - (trade.spread_cost or 0.0)
        final_net_pnl = net_pnl_before_funding - (trade.funding_cost_estimate or 0.0)
        margin_used = trade.margin_used or self._position_size_usd
        final_net_pnl_pct = (final_net_pnl / margin_used) * 100 if margin_used else 0.0
        total_cost_drag = total_fees + (trade.slippage_cost or 0.0) + (trade.spread_cost or 0.0) + (trade.funding_cost_estimate or 0.0)

        entry_dt = datetime.fromisoformat(trade.entry_time)
        exit_dt = datetime.fromisoformat(exit_time)
        duration_seconds = max(0, int((exit_dt - entry_dt).total_seconds()))
        path_candles = self._database.get_candles_between_close_times(
            symbol=trade.symbol,
            timeframe=trade.timeframe,
            start_time_inclusive=trade.entry_time,
            end_time_inclusive=trade.exit_time or exit_time,
        )
        if not path_candles:
            path_candles = [
                StoredCandle(
                    symbol=trade.symbol,
                    timeframe=trade.timeframe,
                    open_time=trade.entry_time,
                    open=trade.entry_price,
                    high=trade.entry_price,
                    low=trade.entry_price,
                    close=trade.entry_price,
                    volume=0.0,
                    close_time=trade.entry_time,
                    provider=trade.provider_used or "UNKNOWN",
                )
            ]
        if trade.direction == "SHORT":
            max_favorable_excursion = max((((trade.entry_price - candle.low) / trade.entry_price) * 100) for candle in path_candles)
            max_adverse_excursion = min((((trade.entry_price - candle.high) / trade.entry_price) * 100) for candle in path_candles)
        else:
            max_favorable_excursion = max((((candle.high - trade.entry_price) / trade.entry_price) * 100) for candle in path_candles)
            max_adverse_excursion = min((((candle.low - trade.entry_price) / trade.entry_price) * 100) for candle in path_candles)

        if final_net_pnl > 0:
            outcome = "WIN_NET"
        elif gross_pnl > 0 and final_net_pnl < 0:
            outcome = "WIN_GROSS_ONLY_NET_LOSS"
        elif final_net_pnl < 0:
            outcome = "LOSS_NET"
        else:
            outcome = "BREAKEVEN_NET"

        self._database.close_simulated_trade(
            trade_id=trade.id,
            status=status,
            exit_time=exit_time,
            exit_price=round(exit_price, 6),
            fees_paid=round(total_fees, 6),
            pnl=round(final_net_pnl, 6),
            pnl_pct=round(final_net_pnl_pct, 6),
            outcome=outcome,
            duration_seconds=duration_seconds,
            max_favorable_excursion=round(max_favorable_excursion, 6),
            max_adverse_excursion=round(max_adverse_excursion, 6),
            reason_exit=reason_exit,
            gross_pnl=round(gross_pnl, 6),
            net_pnl_before_funding=round(net_pnl_before_funding, 6),
            net_pnl=round(final_net_pnl, 6),
            net_pnl_pct=round(final_net_pnl_pct, 6),
            final_net_pnl_after_all_costs=round(final_net_pnl, 6),
            final_net_pnl_after_all_costs_pct=round(final_net_pnl_pct, 6),
            fees_close=round(fees_close, 6),
            total_fees=round(total_fees, 6),
            slippage_cost=round(trade.slippage_cost or 0.0, 6),
            spread_cost=round(trade.spread_cost or 0.0, 6),
            funding_cost_estimate=round(trade.funding_cost_estimate or 0.0, 6),
            total_cost_drag=round(total_cost_drag, 6),
            exit_context=json.dumps(exit_context or {}, ensure_ascii=True),
            cost_snapshot=json.dumps(
                {
                    "gross_pnl": round(gross_pnl, 6),
                    "net_pnl_before_funding": round(net_pnl_before_funding, 6),
                    "final_net_pnl_after_all_costs": round(final_net_pnl, 6),
                    "total_fees": round(total_fees, 6),
                    "slippage_cost": round(trade.slippage_cost or 0.0, 6),
                    "spread_cost": round(trade.spread_cost or 0.0, 6),
                    "funding_cost_estimate": round(trade.funding_cost_estimate or 0.0, 6),
                    "total_cost_drag": round(total_cost_drag, 6),
                },
                ensure_ascii=True,
            ),
        )
        logger.info(
            "Simulated trade closed",
            extra={
                "event": "trade_simulation_close",
                "context": {
                    "trade_id": trade.id,
                    "symbol": trade.symbol,
                    "timeframe": trade.timeframe,
                    "status": status,
                    "entry_price": trade.entry_price,
                    "exit_price": round(exit_price, 6),
                    "gross_pnl": round(gross_pnl, 6),
                    "net_pnl_before_funding": round(net_pnl_before_funding, 6),
                    "final_net_pnl_after_all_costs": round(final_net_pnl, 6),
                    "final_net_pnl_after_all_costs_pct": round(final_net_pnl_pct, 6),
                    "total_cost_drag": round(total_cost_drag, 6),
                    "outcome": outcome,
                    "duration_seconds": duration_seconds,
                    "max_favorable_excursion": round(max_favorable_excursion, 6),
                    "max_adverse_excursion": round(max_adverse_excursion, 6),
                    "exit_time": exit_time,
                },
            },
        )

    def _ensure_trade_protection(self, *, trade: SimulatedTradeRecord) -> SimulatedTradeRecord:
        if trade.stop_loss is not None and trade.take_profit is not None:
            return trade

        baseline_stop_pct = self._stop_loss_pct
        baseline_take_profit_pct = max(self._take_profit_pct, baseline_stop_pct * self._risk_reward_ratio)
        if trade.direction == "SHORT":
            stop_loss = trade.entry_price * (1 + baseline_stop_pct)
            take_profit = trade.entry_price * (1 - baseline_take_profit_pct)
        else:
            stop_loss = trade.entry_price * (1 - baseline_stop_pct)
            take_profit = trade.entry_price * (1 + baseline_take_profit_pct)
        self._database.update_simulated_trade_levels(
            trade_id=trade.id,
            stop_loss=round(stop_loss, 6),
            take_profit=round(take_profit, 6),
            reason_entry=trade.reason_entry or "Backfilled protection levels for legacy open trade",
        )
        return replace(
            trade,
            stop_loss=round(stop_loss, 6),
            take_profit=round(take_profit, 6),
            reason_entry=trade.reason_entry or "Backfilled protection levels for legacy open trade",
        )

    def _maybe_trail_to_breakeven(self, *, trade: SimulatedTradeRecord, latest_candle: StoredCandle) -> SimulatedTradeRecord:
        if trade.break_even_price is None or trade.stop_loss is None or trade.take_profit is None:
            return trade
        if trade.direction == "LONG":
            favorable_trigger = latest_candle.high >= ((trade.entry_price + trade.take_profit) / 2)
            if favorable_trigger and trade.stop_loss < trade.break_even_price:
                new_stop = round(trade.break_even_price, 6)
            else:
                return trade
        else:
            favorable_trigger = latest_candle.low <= ((trade.entry_price + trade.take_profit) / 2)
            if favorable_trigger and trade.stop_loss > trade.break_even_price:
                new_stop = round(trade.break_even_price, 6)
            else:
                return trade
        self._database.update_simulated_trade_levels(
            trade_id=trade.id,
            stop_loss=new_stop,
            take_profit=trade.take_profit,
            reason_entry=trade.reason_entry,
        )
        return replace(trade, stop_loss=new_stop)

    def _entry_fill_price(self, *, direction: str, mark_price: float) -> float:
        spread_component = self._spread_pct / 2
        if direction == "SHORT":
            return mark_price * (1 - self._slippage_pct - spread_component)
        return mark_price * (1 + self._slippage_pct + spread_component)

    def _exit_fill_price(self, *, direction: str, mark_price: float) -> float:
        spread_component = self._spread_pct / 2
        if direction == "SHORT":
            return mark_price * (1 + self._slippage_pct + spread_component)
        return mark_price * (1 - self._slippage_pct - spread_component)
