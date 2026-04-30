from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.database import Database, PaperOrderRecord, PaperPositionRecord, PaperTradeLedgerRecord, SimulatedTradeRecord
from execution.simulated_trade_tracker import SimulatedTradeCycleResult, SimulatedTradeTracker


@dataclass(slots=True, frozen=True)
class ExecutionAgentResult:
    cycle_result: SimulatedTradeCycleResult
    trade: SimulatedTradeRecord | None


class ExecutionSimulatorAgent:
    def __init__(self, database: Database, tracker: SimulatedTradeTracker) -> None:
        self._database = database
        self._tracker = tracker

    def process_cycle(
        self,
        *,
        symbol: str,
        timeframe: str,
        signal: dict[str, Any],
        latest_candle,
        signal_id: int | None,
        current_time: str | None,
        provider_used: str,
    ) -> ExecutionAgentResult:
        result = self._tracker.process_cycle(
            symbol=symbol,
            timeframe=timeframe,
            signal=signal,
            latest_candle=latest_candle,
            signal_id=signal_id,
            current_time=current_time,
            enable_wall_clock_expiry=True,
        )
        trade = self._database.get_open_simulated_trade(symbol, timeframe)
        if result.opened_trade_id and trade is not None:
            self._database.insert_paper_order(
                PaperOrderRecord(
                    timestamp=trade.entry_time,
                    trade_id=trade.id,
                    symbol=trade.symbol,
                    timeframe=trade.timeframe,
                    side=trade.direction,
                    order_type="MARKET_SIMULATED",
                    requested_price=signal["price"],
                    filled_price=trade.entry_price,
                    quantity=(trade.notional_exposure or 0.0) / trade.entry_price if trade.entry_price else 0.0,
                    notional=trade.notional_exposure or 0.0,
                    fees=trade.fees_open or trade.fees_paid,
                    slippage_cost=trade.slippage_cost or 0.0,
                    spread_cost=trade.spread_cost or 0.0,
                    status="FILLED",
                    provider_used=provider_used,
                    reason=str(trade.reason_entry or ""),
                )
            )
            self._database.upsert_paper_position(
                PaperPositionRecord(
                    symbol=trade.symbol,
                    timeframe=trade.timeframe,
                    trade_id=trade.id,
                    direction=trade.direction,
                    quantity=(trade.notional_exposure or 0.0) / trade.entry_price if trade.entry_price else 0.0,
                    entry_price=trade.entry_price,
                    current_price=latest_candle.close,
                    market_value=trade.notional_exposure or 0.0,
                    unrealized_pnl=0.0,
                    exposure_pct=0.0,
                    status="OPEN",
                    opened_at=trade.entry_time,
                    updated_at=current_time or trade.entry_time,
                    provider_used=provider_used,
                )
            )

        if result.closed_trade_id:
            closed_trade = next((item for item in self._database.get_recent_simulated_trades(limit=20) if item.id == result.closed_trade_id), None)
            if closed_trade is not None:
                self._database.close_paper_position(closed_trade.id, current_time or closed_trade.exit_time or closed_trade.updated_at)
                self._database.insert_paper_order(
                    PaperOrderRecord(
                        timestamp=closed_trade.exit_time or (current_time or closed_trade.updated_at),
                        trade_id=closed_trade.id,
                        symbol=closed_trade.symbol,
                        timeframe=closed_trade.timeframe,
                        side=f"EXIT_{closed_trade.direction}",
                        order_type="MARKET_SIMULATED",
                        requested_price=latest_candle.close,
                        filled_price=closed_trade.exit_price or latest_candle.close,
                        quantity=(closed_trade.notional_exposure or 0.0) / closed_trade.entry_price if closed_trade.entry_price else 0.0,
                        notional=closed_trade.notional_exposure or 0.0,
                        fees=closed_trade.fees_close or 0.0,
                        slippage_cost=closed_trade.slippage_cost or 0.0,
                        spread_cost=closed_trade.spread_cost or 0.0,
                        status="FILLED",
                        provider_used=provider_used,
                        reason=str(closed_trade.reason_exit or ""),
                    )
                )
                self._database.insert_paper_trade_ledger(
                    PaperTradeLedgerRecord(
                        trade_id=closed_trade.id,
                        symbol=closed_trade.symbol,
                        timeframe=closed_trade.timeframe,
                        direction=closed_trade.direction,
                        status=closed_trade.status,
                        gross_pnl=closed_trade.gross_pnl or 0.0,
                        net_pnl=closed_trade.net_pnl or closed_trade.pnl or 0.0,
                        total_fees=closed_trade.total_fees or closed_trade.fees_paid,
                        slippage_cost=closed_trade.slippage_cost or 0.0,
                        spread_cost=closed_trade.spread_cost or 0.0,
                        funding_cost_estimate=closed_trade.funding_cost_estimate or 0.0,
                        notes=str(closed_trade.reason_exit or ""),
                        timestamp=closed_trade.exit_time or (current_time or closed_trade.updated_at),
                    )
                )
        return ExecutionAgentResult(cycle_result=result, trade=trade)
