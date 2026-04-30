from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
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
    realized_pnl: float
    total_equity: float
    cash_check: float
    equity_check: float
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
            "realized_pnl": self.realized_pnl,
            "total_equity": self.total_equity,
            "cash_check": self.cash_check,
            "equity_check": self.equity_check,
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
        trade_metrics = self._database.get_simulated_trade_metrics()
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
        total_equity_seed = float(portfolio.get("total_equity", self._settings.simulated_initial_capital))
        starting_capital = float(portfolio.get("starting_capital", self._settings.simulated_initial_capital))
        realized_pnl = float(trade_metrics["total_pnl"])

        unrealized_pnl = 0.0
        gross_exposure = 0.0
        net_exposure = 0.0
        rebuilt_positions = 0
        for trade in open_trades:
            latest_candle = self._database.get_recent_candles(symbol=trade.symbol, timeframe=trade.timeframe, limit=1)
            if not latest_candle:
                notes.append(f"missing mark price for {trade.symbol} {trade.timeframe}")
                continue
            mark = latest_candle[-1].close
            quantity = (trade.notional_exposure or 0.0) / trade.entry_price if trade.entry_price else 0.0
            trade_unrealized = ((trade.entry_price - mark) * quantity) if trade.direction == "SHORT" else ((mark - trade.entry_price) * quantity)
            unrealized_pnl += trade_unrealized
            gross_exposure += trade.notional_exposure or 0.0
            net_exposure += -(trade.notional_exposure or 0.0) if trade.direction == "SHORT" else (trade.notional_exposure or 0.0)

            if mutate:
                exposure_pct = (trade.notional_exposure or 0.0) / max(total_equity_seed, 1.0)
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
                        provider_used=trade.provider_used or latest_candle[-1].provider,
                    )
                )
                rebuilt_positions += 1

        margin_in_use = sum((trade.margin_used or self._settings.simulated_position_size_usd) for trade in open_trades)
        available_cash = starting_capital + realized_pnl - margin_in_use
        total_equity = starting_capital + realized_pnl + unrealized_pnl
        cash_check = available_cash - float(portfolio.get("available_cash", available_cash))
        equity_check = total_equity - float(portfolio.get("total_equity", total_equity))

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
                total_fees_paid=float(trade_metrics["total_fees_paid"]),
                total_slippage_paid=float(trade_metrics["total_slippage_paid"]),
            )
            self._database.upsert_paper_portfolio(updated_portfolio)
            self._database.append_paper_equity_curve(updated_portfolio)

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

        result = "OK"
        if duplicates or orphan_positions or abs(cash_check) > 0.5 or abs(equity_check) > 0.5:
            result = "WARNING"
        if abs(cash_check) > 5 or abs(equity_check) > 5:
            result = "FAIL"

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
            realized_pnl=round(realized_pnl, 6),
            total_equity=round(total_equity, 6),
            cash_check=round(cash_check, 6),
            equity_check=round(equity_check, 6),
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
                    outcome = COALESCE(outcome, 'BREAKEVEN'),
                    reason_exit = COALESCE(reason_exit, 'Reconciled duplicate setup'),
                    updated_at = ?
                WHERE id = ?
                """,
                (timestamp, timestamp, trade_id),
            )
