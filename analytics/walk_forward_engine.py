from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Sequence

from agents.cost_model_agent import CostModelAgent
from agents.delta_agent import DeltaAgent
from agents.market_context_agent import MarketContextAgent
from config.settings import Settings
from core.database import Database, StoredCandle


@dataclass(slots=True, frozen=True)
class WalkForwardSummary:
    selected_relaxation: float
    train_trade_count: int
    test_trade_count: int
    train_net_pnl: float
    test_net_pnl: float
    train_winrate: float
    test_winrate: float
    survived_out_of_sample: bool

    def as_dict(self) -> dict[str, float | int | bool]:
        return {
            "selected_relaxation": self.selected_relaxation,
            "train_trade_count": self.train_trade_count,
            "test_trade_count": self.test_trade_count,
            "train_net_pnl": self.train_net_pnl,
            "test_net_pnl": self.test_net_pnl,
            "train_winrate": self.train_winrate,
            "test_winrate": self.test_winrate,
            "survived_out_of_sample": self.survived_out_of_sample,
        }


class WalkForwardEngine:
    _RELAXATION_SCHEDULE: tuple[float, ...] = (1.0, 0.75, 0.5, 0.3, 0.15, 0.08, 0.04)

    def __init__(
        self,
        *,
        database: Database,
        settings: Settings,
        delta_agent: DeltaAgent,
        market_context_agent: MarketContextAgent,
        cost_model_agent: CostModelAgent,
    ) -> None:
        self._database = database
        self._settings = settings
        self._delta_agent = delta_agent
        self._market_context_agent = market_context_agent
        self._cost_model_agent = cost_model_agent

    def run(
        self,
        *,
        symbols: Sequence[str],
        timeframes: Sequence[str],
        limit: int,
        train_pct: int,
    ) -> dict[str, object]:
        datasets = self._load_datasets(symbols=symbols, timeframes=timeframes, limit=limit)
        best_relaxation = 1.0
        best_train = {"trade_count": 0, "net_pnl": float("-inf"), "winrate": 0.0}

        for relaxation in self._RELAXATION_SCHEDULE:
            aggregate = {"trade_count": 0, "net_pnl": 0.0, "wins": 0}
            for candles in datasets.values():
                train_cut = max(25, int(len(candles) * (train_pct / 100)))
                result = self._simulate_slice(candles=candles[:train_cut], relaxation_factor=relaxation)
                aggregate["trade_count"] += result["trade_count"]
                aggregate["net_pnl"] += result["net_pnl"]
                aggregate["wins"] += result["wins"]
            if aggregate["net_pnl"] > best_train["net_pnl"]:
                best_relaxation = relaxation
                best_train = {
                    "trade_count": aggregate["trade_count"],
                    "net_pnl": aggregate["net_pnl"],
                    "winrate": round((aggregate["wins"] / max(aggregate["trade_count"], 1)) * 100, 2) if aggregate["trade_count"] else 0.0,
                }

        test_aggregate = {"trade_count": 0, "net_pnl": 0.0, "wins": 0}
        for candles in datasets.values():
            train_cut = max(25, int(len(candles) * (train_pct / 100)))
            result = self._simulate_slice(candles=candles[train_cut:], relaxation_factor=best_relaxation)
            test_aggregate["trade_count"] += result["trade_count"]
            test_aggregate["net_pnl"] += result["net_pnl"]
            test_aggregate["wins"] += result["wins"]

        summary = WalkForwardSummary(
            selected_relaxation=best_relaxation,
            train_trade_count=best_train["trade_count"],
            test_trade_count=test_aggregate["trade_count"],
            train_net_pnl=round(best_train["net_pnl"], 6),
            test_net_pnl=round(test_aggregate["net_pnl"], 6),
            train_winrate=best_train["winrate"],
            test_winrate=round((test_aggregate["wins"] / max(test_aggregate["trade_count"], 1)) * 100, 2) if test_aggregate["trade_count"] else 0.0,
            survived_out_of_sample=bool(test_aggregate["trade_count"] and test_aggregate["net_pnl"] >= 0),
        )
        self._persist(symbols=symbols, timeframes=timeframes, limit=limit, train_pct=train_pct, summary=summary)
        return {"summary": summary.as_dict()}

    def _load_datasets(
        self,
        *,
        symbols: Sequence[str],
        timeframes: Sequence[str],
        limit: int,
    ) -> dict[tuple[str, str], list[StoredCandle]]:
        datasets: dict[tuple[str, str], list[StoredCandle]] = {}
        for symbol in symbols:
            for timeframe in timeframes:
                candles = self._database.get_candles(symbol=symbol, timeframe=timeframe)
                if limit > 0:
                    candles = candles[-limit:]
                if len(candles) >= 30:
                    datasets[(symbol, timeframe)] = candles
        return datasets

    def _simulate_slice(self, *, candles: Sequence[StoredCandle], relaxation_factor: float) -> dict[str, float | int]:
        trade_count = 0
        wins = 0
        net_pnl = 0.0
        index = 20
        while index < len(candles) - 5:
            recent_window = candles[max(0, index - 19): index + 1]
            current = candles[index]
            context = self._market_context_agent.evaluate(symbol=current.symbol, timeframe=current.timeframe, candles=recent_window)
            signal = self._delta_agent.evaluate_from_candles(
                symbol=current.symbol,
                timeframe=current.timeframe,
                candles=recent_window,
                market_context=context,
                relaxation_factor=relaxation_factor,
            )
            if str(signal["signal_type"]) not in {"LONG", "SHORT"}:
                index += 1
                continue
            cost = self._cost_model_agent.estimate(
                entry_price=current.close,
                direction=str(signal["signal_type"]),
                position_size_usd=self._settings.simulated_position_size_usd,
                volatility_pct=float(signal.get("volatility_pct", 0.0)),
            )
            exit_index = min(len(candles) - 1, index + self._settings.simulated_max_hold_candles)
            exit_candle = candles[exit_index]
            pnl_pct = self._trade_return_pct(current.close, exit_candle.close, str(signal["signal_type"])) - float(cost.minimum_profitable_move_pct)
            trade_count += 1
            net_pnl += pnl_pct
            wins += 1 if pnl_pct > 0 else 0
            index = exit_index + 1
        return {"trade_count": trade_count, "wins": wins, "net_pnl": net_pnl}

    def _persist(
        self,
        *,
        symbols: Sequence[str],
        timeframes: Sequence[str],
        limit: int,
        train_pct: int,
        summary: WalkForwardSummary,
    ) -> None:
        timestamp = datetime.now(timezone.utc).isoformat()
        with self._database.connection() as conn:
            conn.execute("DELETE FROM walk_forward_results")
            conn.execute(
                """
                INSERT INTO walk_forward_results (
                    timestamp, train_pct, limit_used, symbols, timeframes, selected_relaxation,
                    train_trade_count, test_trade_count, train_net_pnl, test_net_pnl, train_winrate,
                    test_winrate, survived_out_of_sample, raw_payload, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    timestamp,
                    float(train_pct),
                    limit,
                    json.dumps(list(symbols), ensure_ascii=True),
                    json.dumps(list(timeframes), ensure_ascii=True),
                    summary.selected_relaxation,
                    summary.train_trade_count,
                    summary.test_trade_count,
                    summary.train_net_pnl,
                    summary.test_net_pnl,
                    summary.train_winrate,
                    summary.test_winrate,
                    int(summary.survived_out_of_sample),
                    json.dumps(summary.as_dict(), ensure_ascii=True),
                    timestamp,
                ),
            )

    @staticmethod
    def _trade_return_pct(entry: float, exit_price: float, direction: str) -> float:
        if entry == 0:
            return 0.0
        move = ((exit_price - entry) / entry) * 100
        return -move if direction == "SHORT" else move
