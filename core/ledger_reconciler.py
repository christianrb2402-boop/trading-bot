from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Any

from config.settings import Settings
from core.database import Database, ErrorEventRecord, PaperPortfolioRecord, PaperPositionRecord


@dataclass(slots=True, frozen=True)
class LedgerConsistencyReport:
    open_positions_count: int
    open_simulated_trades_count: int
    orphan_positions: int
    duplicated_positions: int
    gross_exposure: float
    net_exposure: float
    unrealized_pnl: float
    available_cash: float
    actual_available_cash: float
    reserved_capital_total: float
    notional_open_positions: float
    fees_paid_total: float
    realized_pnl: float
    total_equity: float
    actual_total_equity: float
    cash_check: float
    equity_check: float
    latest_position_notional: float
    latest_entry_fees: float
    latest_entry_slippage: float
    latest_entry_spread: float
    latest_available_cash_before_open: float
    latest_available_cash_after_open: float
    latest_reserved_cash_after_open: float
    latest_equity_before_open: float
    latest_equity_after_open: float
    ledger_fail_reason: str
    reconciled_positions: int
    reconciled_duplicates: int
    result: str
    notes: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "open_positions_count": self.open_positions_count,
            "open_simulated_trades_count": self.open_simulated_trades_count,
            "orphan_positions": self.orphan_positions,
            "duplicated_positions": self.duplicated_positions,
            "gross_exposure": self.gross_exposure,
            "net_exposure": self.net_exposure,
            "unrealized_pnl": self.unrealized_pnl,
            "available_cash": self.available_cash,
            "actual_available_cash": self.actual_available_cash,
            "reserved_capital_total": self.reserved_capital_total,
            "notional_open_positions": self.notional_open_positions,
            "fees_paid_total": self.fees_paid_total,
            "realized_pnl": self.realized_pnl,
            "total_equity": self.total_equity,
            "actual_total_equity": self.actual_total_equity,
            "cash_check": self.cash_check,
            "equity_check": self.equity_check,
            "latest_position_notional": self.latest_position_notional,
            "latest_entry_fees": self.latest_entry_fees,
            "latest_entry_slippage": self.latest_entry_slippage,
            "latest_entry_spread": self.latest_entry_spread,
            "latest_available_cash_before_open": self.latest_available_cash_before_open,
            "latest_available_cash_after_open": self.latest_available_cash_after_open,
            "latest_reserved_cash_after_open": self.latest_reserved_cash_after_open,
            "latest_equity_before_open": self.latest_equity_before_open,
            "latest_equity_after_open": self.latest_equity_after_open,
            "ledger_fail_reason": self.ledger_fail_reason,
            "reconciled_positions": self.reconciled_positions,
            "reconciled_duplicates": self.reconciled_duplicates,
            "result": self.result,
            "notes": self.notes,
        }


class LedgerReconciler:
    def __init__(self, database: Database, settings: Settings) -> None:
        self._database = database
        self._settings = settings

    def inspect(self) -> LedgerConsistencyReport:
        return self._run(mutate=False)

    def reconcile(self) -> LedgerConsistencyReport:
        return self._run(mutate=True)

    def _run(self, *, mutate: bool) -> LedgerConsistencyReport:
        now = datetime.now(timezone.utc).isoformat()
        open_trades = self._database.get_open_simulated_trades()
        open_positions = self._database.get_open_paper_positions()
        portfolio = self._database.get_paper_portfolio() or {}
        notes: list[str] = []

        open_trade_ids = {trade.id for trade in open_trades}
        orphan_positions = [position for position in open_positions if int(position["trade_id"]) not in open_trade_ids]

        duplicates = self._find_duplicate_open_trades()
        reconciled_positions = 0
        reconciled_duplicates = 0

        if mutate:
            for position in orphan_positions:
                self._mark_position_reconciled(position_id=int(position["id"]), timestamp=now)
                reconciled_positions += 1
            for trade_id in duplicates[1:]:
                self._mark_trade_reconciled(trade_id=trade_id, timestamp=now)
                reconciled_duplicates += 1

        open_trades = self._database.get_open_simulated_trades()
        starting_capital = float(portfolio.get("starting_capital", self._settings.simulated_initial_capital))
        closed_trades = self._database.get_closed_simulated_trades()
        realized_pnl = sum(
            float(
                trade.final_net_pnl_after_all_costs
                if trade.final_net_pnl_after_all_costs is not None
                else (trade.net_pnl if trade.net_pnl is not None else (trade.pnl or 0.0))
            )
            for trade in closed_trades
        )

        unrealized_pnl = 0.0
        gross_exposure = 0.0
        net_exposure = 0.0
        reserved_capital_total = 0.0
        notional_open_positions = 0.0
        rebuilt_positions = 0
        for trade in open_trades:
            latest_candle = self._database.get_recent_candles(symbol=trade.symbol, timeframe=trade.timeframe, limit=1)
            if not latest_candle:
                notes.append(f"missing mark price for {trade.symbol} {trade.timeframe}")
            mark = latest_candle[-1].close if latest_candle else trade.entry_price
            quantity = (trade.notional_exposure or 0.0) / trade.entry_price if trade.entry_price else 0.0
            trade_unrealized = ((trade.entry_price - mark) * quantity) if trade.direction == "SHORT" else ((mark - trade.entry_price) * quantity)
            unrealized_pnl += trade_unrealized
            gross_exposure += trade.notional_exposure or 0.0
            net_exposure += -(trade.notional_exposure or 0.0) if trade.direction == "SHORT" else (trade.notional_exposure or 0.0)
            reserved_capital_total += trade.margin_used or self._settings.simulated_position_size_usd
            notional_open_positions += trade.notional_exposure or 0.0

            if mutate:
                exposure_pct = (trade.notional_exposure or 0.0) / max(starting_capital + realized_pnl + unrealized_pnl, 1.0)
                self._database.upsert_paper_position(
                    PaperPositionRecord(
                        symbol=trade.symbol,
                        timeframe=trade.timeframe,
                        trade_id=trade.id,
                        direction=trade.direction,
                        quantity=round(quantity, 8),
                        entry_price=trade.entry_price,
                        current_price=round(mark, 6),
                        market_value=round(quantity * mark, 6),
                        unrealized_pnl=round(trade_unrealized, 6),
                        exposure_pct=round(exposure_pct, 6),
                        status="OPEN",
                        opened_at=trade.entry_time,
                        updated_at=now,
                        provider_used=trade.provider_used or (latest_candle[-1].provider if latest_candle else "UNKNOWN"),
                    )
                )
                rebuilt_positions += 1

        open_entry_fees = sum(float(trade.fees_open or trade.fees_paid or 0.0) for trade in open_trades)
        closed_total_fees = sum(float(trade.total_fees or trade.fees_paid or 0.0) for trade in closed_trades)
        fees_paid_total = closed_total_fees + open_entry_fees
        available_cash = starting_capital + realized_pnl - reserved_capital_total
        total_equity = starting_capital + realized_pnl + unrealized_pnl
        actual_available_cash = float(portfolio.get("available_cash", available_cash))
        actual_total_equity = float(portfolio.get("total_equity", total_equity))
        cash_check = available_cash - actual_available_cash
        equity_check = total_equity - actual_total_equity

        latest_trade = max(open_trades, key=lambda item: item.entry_time, default=None)
        latest_accounting: dict[str, object] = {}
        latest_position_notional = 0.0
        latest_entry_fees = 0.0
        latest_entry_slippage = 0.0
        latest_entry_spread = 0.0
        latest_available_cash_before_open = 0.0
        latest_available_cash_after_open = 0.0
        latest_reserved_cash_after_open = 0.0
        latest_equity_before_open = 0.0
        latest_equity_after_open = 0.0
        if latest_trade is not None:
            latest_position_notional = float(latest_trade.notional_exposure or 0.0)
            latest_entry_fees = float(latest_trade.fees_open or latest_trade.fees_paid or 0.0)
            latest_entry_slippage = float(latest_trade.slippage_cost or 0.0)
            latest_entry_spread = float(latest_trade.spread_cost or 0.0)
            try:
                entry_context = json.loads(latest_trade.entry_context or "{}")
            except json.JSONDecodeError:
                entry_context = {}
            latest_accounting = entry_context.get("accounting", {}) if isinstance(entry_context, dict) else {}
            if isinstance(latest_accounting, dict):
                latest_available_cash_before_open = float(latest_accounting.get("available_cash_before_open", 0.0) or 0.0)
                latest_available_cash_after_open = float(latest_accounting.get("expected_cash_after_open", actual_available_cash) or 0.0)
                latest_reserved_cash_after_open = float(latest_accounting.get("reserved_cash_after_open", reserved_capital_total) or 0.0)
                latest_equity_before_open = float(latest_accounting.get("equity_before_open", 0.0) or 0.0)
            latest_equity_after_open = total_equity
            if latest_available_cash_before_open == 0.0:
                inferred_margin = float(latest_trade.margin_used or self._settings.simulated_position_size_usd)
                if latest_available_cash_after_open == 0.0:
                    latest_available_cash_after_open = actual_available_cash
                latest_available_cash_before_open = actual_available_cash + inferred_margin
                latest_reserved_cash_after_open = reserved_capital_total
            if latest_equity_before_open == 0.0:
                latest_equity_before_open = total_equity - unrealized_pnl

        if mutate:
            updated_portfolio = PaperPortfolioRecord(
                timestamp=now,
                starting_capital=round(starting_capital, 6),
                available_cash=round(available_cash, 6),
                realized_pnl=round(realized_pnl, 6),
                unrealized_pnl=round(unrealized_pnl, 6),
                total_equity=round(total_equity, 6),
                drawdown=float(portfolio.get("drawdown", 0.0)),
                max_drawdown=float(portfolio.get("max_drawdown", 0.0)),
                gross_exposure=round(gross_exposure, 6),
                net_exposure=round(net_exposure, 6),
                open_positions=len(open_trades),
                total_fees_paid=round(fees_paid_total, 6),
                total_slippage_paid=round(
                    sum(float(trade.slippage_cost or 0.0) for trade in closed_trades)
                    + sum(float(trade.slippage_cost or 0.0) for trade in open_trades)
                    + sum(float(trade.spread_cost or 0.0) for trade in open_trades),
                    6,
                ),
            )
            self._database.upsert_paper_portfolio(updated_portfolio)
            self._database.append_paper_equity_curve(updated_portfolio)
            actual_available_cash = available_cash
            actual_total_equity = total_equity
            cash_check = 0.0
            equity_check = 0.0

        if orphan_positions:
            notes.append(f"orphan positions detected: {len(orphan_positions)}")
        if duplicates:
            notes.append(f"duplicate open trades detected: {len(duplicates)}")
        if abs(cash_check) > 0.5:
            notes.append(f"cash drift detected: {round(cash_check, 6)}")
        if abs(equity_check) > 0.5:
            notes.append(f"equity drift detected: {round(equity_check, 6)}")
        if rebuilt_positions and mutate:
            notes.append(f"rebuilt {rebuilt_positions} paper positions from open simulated trades")

        if not notes:
            notes.append("ledger is internally consistent")

        ledger_fail_reason = ""
        result = "OK"
        if duplicates or orphan_positions or abs(cash_check) > 0.5 or abs(equity_check) > 0.5:
            result = "WARNING"
        if abs(cash_check) > 5 or abs(equity_check) > 5:
            result = "FAIL"
        if result != "OK":
            ledger_fail_reason = notes[0]

        if mutate:
            self._database.insert_error_event(
                ErrorEventRecord(
                    timestamp=now,
                    component="ledger_reconciler",
                    symbol=None,
                    error_type=f"LEDGER_{result}",
                    error_message="; ".join(notes),
                    recoverable=result != "FAIL",
                )
            )

        return LedgerConsistencyReport(
            open_positions_count=len(self._database.get_open_paper_positions()),
            open_simulated_trades_count=len(open_trades),
            orphan_positions=len(orphan_positions),
            duplicated_positions=max(len(duplicates) - 1, 0),
            gross_exposure=round(gross_exposure, 6),
            net_exposure=round(net_exposure, 6),
            unrealized_pnl=round(unrealized_pnl, 6),
            available_cash=round(available_cash, 6),
            actual_available_cash=round(actual_available_cash, 6),
            reserved_capital_total=round(reserved_capital_total, 6),
            notional_open_positions=round(notional_open_positions, 6),
            fees_paid_total=round(fees_paid_total, 6),
            realized_pnl=round(realized_pnl, 6),
            total_equity=round(total_equity, 6),
            actual_total_equity=round(actual_total_equity, 6),
            cash_check=round(cash_check, 6),
            equity_check=round(equity_check, 6),
            latest_position_notional=round(latest_position_notional, 6),
            latest_entry_fees=round(latest_entry_fees, 6),
            latest_entry_slippage=round(latest_entry_slippage, 6),
            latest_entry_spread=round(latest_entry_spread, 6),
            latest_available_cash_before_open=round(latest_available_cash_before_open, 6),
            latest_available_cash_after_open=round(latest_available_cash_after_open, 6),
            latest_reserved_cash_after_open=round(latest_reserved_cash_after_open, 6),
            latest_equity_before_open=round(latest_equity_before_open, 6),
            latest_equity_after_open=round(latest_equity_after_open, 6),
            ledger_fail_reason=ledger_fail_reason,
            reconciled_positions=reconciled_positions,
            reconciled_duplicates=reconciled_duplicates,
            result=result,
            notes=tuple(notes),
        )

    def _find_duplicate_open_trades(self) -> list[int]:
        with self._database.connection() as conn:
            rows = conn.execute(
                """
                SELECT id
                FROM simulated_trades
                WHERE COALESCE(status, 'OPEN') = 'OPEN'
                ORDER BY symbol, timeframe, direction, COALESCE(entry_time, timestamp_entry), COALESCE(setup_signature, ''), id
                """
            ).fetchall()
        duplicates: list[int] = []
        seen: set[tuple[str, str, str, str, str]] = set()
        for row in rows:
            trade = next((item for item in self._database.get_open_simulated_trades() if item.id == int(row["id"])), None)
            if trade is None:
                continue
            key = (
                trade.symbol,
                trade.timeframe,
                trade.direction,
                trade.entry_time,
                trade.setup_signature or "",
            )
            if key in seen:
                duplicates.append(trade.id)
            else:
                seen.add(key)
        return duplicates

    def _mark_position_reconciled(self, *, position_id: int, timestamp: str) -> None:
        with self._database.connection() as conn:
            conn.execute(
                """
                UPDATE paper_positions
                SET status = 'RECONCILED',
                    updated_at = ?
                WHERE id = ?
                """,
                (timestamp, position_id),
            )

    def _mark_trade_reconciled(self, *, trade_id: int, timestamp: str) -> None:
        with self._database.connection() as conn:
            conn.execute(
                """
                UPDATE simulated_trades
                SET status = 'RECONCILED',
                    exit_time = COALESCE(exit_time, ?),
                    exit_price = COALESCE(exit_price, entry_price),
                    net_pnl = COALESCE(net_pnl, 0),
                    pnl = COALESCE(pnl, 0),
                    net_pnl_pct = COALESCE(net_pnl_pct, 0),
                    pnl_pct = COALESCE(pnl_pct, 0),
                    final_net_pnl_after_all_costs = COALESCE(final_net_pnl_after_all_costs, net_pnl, pnl, 0),
                    final_net_pnl_after_all_costs_pct = COALESCE(final_net_pnl_after_all_costs_pct, net_pnl_pct, pnl_pct, 0),
                    outcome = COALESCE(outcome, 'BREAKEVEN_NET'),
                    reason_exit = COALESCE(reason_exit, 'Reconciled duplicate setup'),
                    updated_at = ?
                WHERE id = ?
                """,
                (timestamp, timestamp, trade_id),
            )
