from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
import random
from typing import Sequence

from analytics.backtest_engine import BacktestEngine
from config.settings import Settings
from core.database import Database, StoredCandle


@dataclass(slots=True, frozen=True)
class BenchmarkSummary:
    benchmark_name: str
    trade_count: int
    winrate: float
    max_drawdown: float
    profit_factor: float
    average_trade: float
    total_net_pnl: float
    total_cost: float
    sharpe_simple: float
    edge_vs_strategy: float | None

    def as_dict(self) -> dict[str, str | int | float | None]:
        return {
            "benchmark_name": self.benchmark_name,
            "trade_count": self.trade_count,
            "winrate": self.winrate,
            "max_drawdown": self.max_drawdown,
            "profit_factor": self.profit_factor,
            "average_trade": self.average_trade,
            "total_net_pnl": self.total_net_pnl,
            "total_cost": self.total_cost,
            "sharpe_simple": self.sharpe_simple,
            "edge_vs_strategy": self.edge_vs_strategy,
        }


class BenchmarkEngine:
    def __init__(self, *, database: Database, settings: Settings, backtest_engine: BacktestEngine) -> None:
        self._database = database
        self._settings = settings
        self._backtest_engine = backtest_engine

    def run(
        self,
        *,
        symbols: Sequence[str],
        timeframes: Sequence[str],
        limit: int,
        min_trades: int,
    ) -> dict[str, object]:
        strategy_result = self._backtest_engine.run(
            symbols=symbols,
            timeframes=timeframes,
            limit=limit,
            min_trades=min_trades,
        )
        strategy_metrics = strategy_result["trade_metrics"]
        strategy_summary = BenchmarkSummary(
            benchmark_name="BOT_STRATEGY",
            trade_count=int(strategy_metrics["closed_trades"]),
            winrate=float(strategy_metrics["winrate"]),
            max_drawdown=self._max_drawdown_from_closed_trades(),
            profit_factor=self._profit_factor_from_closed_trades(),
            average_trade=float(strategy_metrics["average_pnl"]),
            total_net_pnl=float(strategy_metrics["total_pnl"]),
            total_cost=float(strategy_metrics["total_fees_paid"]) + float(strategy_metrics["total_slippage_paid"]) + float(strategy_metrics["total_spread_paid"]),
            sharpe_simple=self._simple_sharpe_from_closed_trades(),
            edge_vs_strategy=0.0,
        )

        benchmark_rows = [strategy_summary]
        buy_hold = self._buy_and_hold(symbols=symbols, timeframes=timeframes, limit=limit, strategy_total=strategy_summary.total_net_pnl)
        benchmark_rows.append(buy_hold)
        random_baseline = self._random_baseline(symbols=symbols, timeframes=timeframes, limit=limit, trade_count=max(strategy_summary.trade_count, 20), strategy_total=strategy_summary.total_net_pnl)
        benchmark_rows.append(random_baseline)
        trend_baseline = self._trend_baseline(symbols=symbols, timeframes=timeframes, limit=limit, strategy_total=strategy_summary.total_net_pnl)
        benchmark_rows.append(trend_baseline)
        benchmark_rows.append(
            BenchmarkSummary(
                benchmark_name="NO_TRADE",
                trade_count=0,
                winrate=0.0,
                max_drawdown=0.0,
                profit_factor=0.0,
                average_trade=0.0,
                total_net_pnl=0.0,
                total_cost=0.0,
                sharpe_simple=0.0,
                edge_vs_strategy=round(0.0 - strategy_summary.total_net_pnl, 6),
            )
        )

        self._persist_rows(symbols=symbols, timeframes=timeframes, rows=benchmark_rows)
        return {
            "strategy_result": strategy_result,
            "benchmarks": [row.as_dict() for row in benchmark_rows],
        }

    def _buy_and_hold(self, *, symbols: Sequence[str], timeframes: Sequence[str], limit: int, strategy_total: float) -> BenchmarkSummary:
        pnl_values: list[float] = []
        total_cost = 0.0
        for symbol in symbols:
            for timeframe in timeframes:
                candles = self._database.get_candles(symbol=symbol, timeframe=timeframe)
                if limit > 0:
                    candles = candles[-limit:]
                if len(candles) < 2:
                    continue
                entry = candles[0].close
                exit_price = candles[-1].close
                gross_pct = ((exit_price - entry) / entry) * 100 if entry else 0.0
                cost_pct = self._round_trip_cost_pct()
                pnl_values.append(gross_pct - cost_pct)
                total_cost += cost_pct
        return self._summarize("BUY_AND_HOLD", pnl_values, total_cost, strategy_total)

    def _random_baseline(
        self,
        *,
        symbols: Sequence[str],
        timeframes: Sequence[str],
        limit: int,
        trade_count: int,
        strategy_total: float,
    ) -> BenchmarkSummary:
        rng = random.Random(42)
        pnl_values: list[float] = []
        total_cost = 0.0
        all_datasets: list[tuple[str, str, list[StoredCandle]]] = []
        for symbol in symbols:
            for timeframe in timeframes:
                candles = self._database.get_candles(symbol=symbol, timeframe=timeframe)
                if limit > 0:
                    candles = candles[-limit:]
                if len(candles) >= 10:
                    all_datasets.append((symbol, timeframe, candles))
        if not all_datasets:
            return self._summarize("RANDOM_ENTRY", [], 0.0, strategy_total)
        for _ in range(trade_count):
            _, _, candles = rng.choice(all_datasets)
            entry_index = rng.randint(0, len(candles) - 6)
            horizon = rng.randint(3, min(self._settings.simulated_max_hold_candles, 10))
            exit_index = min(len(candles) - 1, entry_index + horizon)
            direction = rng.choice(("LONG", "SHORT"))
            pnl = self._trade_return_pct(candles[entry_index].close, candles[exit_index].close, direction)
            pnl_values.append(pnl - self._round_trip_cost_pct())
            total_cost += self._round_trip_cost_pct()
        return self._summarize("RANDOM_ENTRY", pnl_values, total_cost, strategy_total)

    def _trend_baseline(self, *, symbols: Sequence[str], timeframes: Sequence[str], limit: int, strategy_total: float) -> BenchmarkSummary:
        pnl_values: list[float] = []
        total_cost = 0.0
        for symbol in symbols:
            for timeframe in timeframes:
                candles = self._database.get_candles(symbol=symbol, timeframe=timeframe)
                if limit > 0:
                    candles = candles[-limit:]
                if len(candles) < 30:
                    continue
                for index in range(20, len(candles) - 5, 10):
                    lookback = candles[index - 20:index]
                    entry_candle = candles[index]
                    exit_candle = candles[min(len(candles) - 1, index + 5)]
                    trend = "LONG" if entry_candle.close >= lookback[0].close else "SHORT"
                    pnl = self._trade_return_pct(entry_candle.close, exit_candle.close, trend)
                    pnl_values.append(pnl - self._round_trip_cost_pct())
                    total_cost += self._round_trip_cost_pct()
        return self._summarize("TREND_FOLLOWING_BASELINE", pnl_values, total_cost, strategy_total)

    def _summarize(self, name: str, pnl_values: Sequence[float], total_cost: float, strategy_total: float) -> BenchmarkSummary:
        if not pnl_values:
            return BenchmarkSummary(name, 0, 0.0, 0.0, 0.0, 0.0, 0.0, round(total_cost, 6), 0.0, round(0.0 - strategy_total, 6))
        wins = sum(1 for pnl in pnl_values if pnl > 0)
        gross_profit = sum(pnl for pnl in pnl_values if pnl > 0)
        gross_loss = abs(sum(pnl for pnl in pnl_values if pnl < 0))
        cumulative = 0.0
        peak = 0.0
        max_drawdown = 0.0
        for pnl in pnl_values:
            cumulative += pnl
            peak = max(peak, cumulative)
            max_drawdown = min(max_drawdown, cumulative - peak)
        average_trade = sum(pnl_values) / len(pnl_values)
        sharpe = 0.0
        if len(pnl_values) > 1:
            mean = average_trade
            variance = sum((pnl - mean) ** 2 for pnl in pnl_values) / (len(pnl_values) - 1)
            std = math.sqrt(variance)
            sharpe = mean / std if std else 0.0
        return BenchmarkSummary(
            benchmark_name=name,
            trade_count=len(pnl_values),
            winrate=round((wins / len(pnl_values)) * 100, 2),
            max_drawdown=round(max_drawdown, 6),
            profit_factor=round((gross_profit / gross_loss), 6) if gross_loss else round(gross_profit, 6),
            average_trade=round(average_trade, 6),
            total_net_pnl=round(sum(pnl_values), 6),
            total_cost=round(total_cost, 6),
            sharpe_simple=round(sharpe, 6),
            edge_vs_strategy=round(sum(pnl_values) - strategy_total, 6),
        )

    def _persist_rows(self, *, symbols: Sequence[str], timeframes: Sequence[str], rows: Sequence[BenchmarkSummary]) -> None:
        timestamp = datetime.now(timezone.utc).isoformat()
        with self._database.connection() as conn:
            conn.execute("DELETE FROM benchmark_results")
            for row in rows:
                conn.execute(
                    """
                    INSERT INTO benchmark_results (
                        timestamp, benchmark_name, symbols, timeframes, trade_count, winrate, max_drawdown,
                        profit_factor, average_trade, total_net_pnl, total_cost, sharpe_simple, edge_vs_strategy,
                        raw_payload, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        timestamp,
                        row.benchmark_name,
                        json.dumps(list(symbols), ensure_ascii=True),
                        json.dumps(list(timeframes), ensure_ascii=True),
                        row.trade_count,
                        row.winrate,
                        row.max_drawdown,
                        row.profit_factor,
                        row.average_trade,
                        row.total_net_pnl,
                        row.total_cost,
                        row.sharpe_simple,
                        row.edge_vs_strategy,
                        json.dumps(row.as_dict(), ensure_ascii=True),
                        timestamp,
                    ),
                )

    def _profit_factor_from_closed_trades(self) -> float:
        trades = self._database.get_closed_simulated_trades()
        profits = sum((trade.net_pnl or trade.pnl or 0.0) for trade in trades if (trade.net_pnl or trade.pnl or 0.0) > 0)
        losses = abs(sum((trade.net_pnl or trade.pnl or 0.0) for trade in trades if (trade.net_pnl or trade.pnl or 0.0) < 0))
        return round((profits / losses), 6) if losses else round(profits, 6)

    def _simple_sharpe_from_closed_trades(self) -> float:
        trades = self._database.get_closed_simulated_trades()
        returns = [(trade.net_pnl_pct if trade.net_pnl_pct is not None else (trade.pnl_pct or 0.0)) for trade in trades]
        if len(returns) < 2:
            return 0.0
        mean = sum(returns) / len(returns)
        variance = sum((value - mean) ** 2 for value in returns) / (len(returns) - 1)
        std = math.sqrt(variance)
        return round((mean / std), 6) if std else 0.0

    def _max_drawdown_from_closed_trades(self) -> float:
        trades = self._database.get_closed_simulated_trades()
        cumulative = 0.0
        peak = 0.0
        drawdown = 0.0
        for trade in trades:
            cumulative += trade.net_pnl if trade.net_pnl is not None else (trade.pnl or 0.0)
            peak = max(peak, cumulative)
            drawdown = min(drawdown, cumulative - peak)
        return round(drawdown, 6)

    def _round_trip_cost_pct(self) -> float:
        return round(
            (
                (self._settings.simulated_taker_fee_pct * 2)
                + (self._settings.simulated_slippage_pct * 2)
                + self._settings.simulated_spread_pct
                + self._settings.simulated_funding_rate_estimate
            ) * 100,
            6,
        )

    @staticmethod
    def _trade_return_pct(entry: float, exit_price: float, direction: str) -> float:
        if entry == 0:
            return 0.0
        move = ((exit_price - entry) / entry) * 100
        return -move if direction == "SHORT" else move
