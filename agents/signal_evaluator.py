from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Sequence

from agents.delta_agent import DeltaAgent, HistoricalDeltaSignal
from core.database import Database, SignalEvaluationRecord, StoredCandle


@dataclass(slots=True, frozen=True)
class SignalEvaluationSummary:
    symbol: str
    timeframe: str
    horizon: int
    total_signals: int
    winrate: float
    average_return: float
    median_return: float
    average_drawdown: float
    average_max_favorable_excursion: float

    def as_dict(self) -> dict[str, str | int | float]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "horizon": self.horizon,
            "total_signals": self.total_signals,
            "winrate": self.winrate,
            "average_return": self.average_return,
            "median_return": self.median_return,
            "average_drawdown": self.average_drawdown,
            "average_max_favorable_excursion": self.average_max_favorable_excursion,
        }


@dataclass(slots=True, frozen=True)
class DirectionalPerformanceSummary:
    symbol: str
    timeframe: str
    horizon: int
    direction: str
    total_signals: int
    winrate: float
    average_return: float

    def as_dict(self) -> dict[str, str | int | float]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "horizon": self.horizon,
            "direction": self.direction,
            "total_signals": self.total_signals,
            "winrate": self.winrate,
            "average_return": self.average_return,
        }


@dataclass(slots=True, frozen=True)
class ThresholdOptimizationSummary:
    symbol: str
    timeframe: str
    horizon: int
    threshold: float
    total_signals: int
    winrate: float
    average_return: float

    def as_dict(self) -> dict[str, str | int | float]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "horizon": self.horizon,
            "threshold": self.threshold,
            "total_signals": self.total_signals,
            "winrate": self.winrate,
            "average_return": self.average_return,
        }


class SignalEvaluator:
    def __init__(self, database: Database, delta_agent: DeltaAgent) -> None:
        self._database = database
        self._delta_agent = delta_agent

    def evaluate_symbol(
        self,
        symbol: str,
        timeframe: str,
        horizons: Sequence[int] = (5, 10, 15),
    ) -> dict[str, str | list[dict[str, str | int | float]] | int]:
        signal_count, evaluations, skipped_incomplete = self._collect_signal_evaluations(
            delta_agent=self._delta_agent,
            symbol=symbol,
            timeframe=timeframe,
            horizons=horizons,
        )
        self._database.delete_signal_evaluations(agent_name="delta", symbol=symbol, timeframe=timeframe)
        insert_result = self._database.upsert_signal_evaluations(evaluations)
        summaries = [self._build_summary(symbol, timeframe, horizon, evaluations) for horizon in horizons]

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "signal_count": signal_count,
            "evaluations_saved": insert_result.inserted,
            "evaluations_updated": insert_result.updated,
            "skipped_incomplete": skipped_incomplete,
            "summaries": [summary.as_dict() for summary in summaries],
        }

    def evaluate_symbol_by_direction(
        self,
        symbol: str,
        timeframe: str,
        horizons: Sequence[int] = (5, 10, 15),
    ) -> dict[str, str | int | list[dict[str, str | int | float]]]:
        base_result = self.evaluate_symbol(symbol=symbol, timeframe=timeframe, horizons=horizons)
        evaluations = self._collect_signal_evaluations(
            delta_agent=self._delta_agent,
            symbol=symbol,
            timeframe=timeframe,
            horizons=horizons,
        )[1]
        directional_summaries = [
            self._build_directional_summary(symbol, timeframe, horizon, "LONG", evaluations)
            for horizon in horizons
        ]

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "signal_count": base_result["signal_count"],
            "evaluations_saved": base_result["evaluations_saved"],
            "evaluations_updated": base_result["evaluations_updated"],
            "skipped_incomplete": base_result["skipped_incomplete"],
            "directional_summaries": [summary.as_dict() for summary in directional_summaries],
        }

    def optimize_thresholds(
        self,
        symbol: str,
        timeframe: str,
        thresholds: Sequence[float],
        horizons: Sequence[int] = (5, 10, 15),
    ) -> dict[str, str | list[dict[str, str | int | float]]]:
        summaries: list[ThresholdOptimizationSummary] = []

        for threshold in thresholds:
            delta_agent = DeltaAgent(database=self._database, threshold=threshold)
            _, evaluations, _ = self._collect_signal_evaluations(
                delta_agent=delta_agent,
                symbol=symbol,
                timeframe=timeframe,
                horizons=horizons,
            )
            for horizon in horizons:
                summaries.append(
                    self._build_threshold_summary(
                        symbol=symbol,
                        timeframe=timeframe,
                        horizon=horizon,
                        threshold=threshold,
                        evaluations=evaluations,
                    )
                )

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "threshold_summaries": [summary.as_dict() for summary in summaries],
        }

    def _evaluate_signal(
        self,
        *,
        signal: HistoricalDeltaSignal,
        future_candles: Sequence[StoredCandle],
        horizon: int,
    ) -> SignalEvaluationRecord:
        entry_price = signal.entry_price
        favorable_returns = [
            self._directional_return(entry_price, candle.high if signal.direction == "LONG" else candle.low, signal.direction)
            for candle in future_candles
        ]
        adverse_returns = [
            self._directional_return(entry_price, candle.low if signal.direction == "LONG" else candle.high, signal.direction)
            for candle in future_candles
        ]
        close_return = self._directional_return(entry_price, future_candles[-1].close, signal.direction)

        return SignalEvaluationRecord(
            agent_name="delta",
            symbol=signal.symbol,
            timeframe=signal.timeframe,
            signal_time=signal.open_time,
            direction=signal.direction,
            horizon_candles=horizon,
            entry_price=entry_price,
            k_value=signal.k,
            max_favorable_return=round(max(favorable_returns), 6),
            min_return=round(min(adverse_returns), 6),
            close_return=round(close_return, 6),
            is_positive=close_return > 0,
        )

    def _build_summary(
        self,
        symbol: str,
        timeframe: str,
        horizon: int,
        evaluations: Sequence[SignalEvaluationRecord],
    ) -> SignalEvaluationSummary:
        horizon_rows = [
            evaluation
            for evaluation in evaluations
            if evaluation.symbol == symbol
            and evaluation.timeframe == timeframe
            and evaluation.horizon_candles == horizon
        ]
        if not horizon_rows:
            return SignalEvaluationSummary(
                symbol=symbol,
                timeframe=timeframe,
                horizon=horizon,
                total_signals=0,
                winrate=0.0,
                average_return=0.0,
                median_return=0.0,
                average_drawdown=0.0,
                average_max_favorable_excursion=0.0,
            )

        close_returns = [row.close_return for row in horizon_rows]
        drawdowns = [row.min_return for row in horizon_rows]
        favorable = [row.max_favorable_return for row in horizon_rows]
        wins = sum(1 for row in horizon_rows if row.is_positive)

        return SignalEvaluationSummary(
            symbol=symbol,
            timeframe=timeframe,
            horizon=horizon,
            total_signals=len(horizon_rows),
            winrate=round((wins / len(horizon_rows)) * 100, 2),
            average_return=round(sum(close_returns) / len(close_returns), 6),
            median_return=round(float(median(close_returns)), 6),
            average_drawdown=round(sum(drawdowns) / len(drawdowns), 6),
            average_max_favorable_excursion=round(sum(favorable) / len(favorable), 6),
        )

    def _build_directional_summary(
        self,
        symbol: str,
        timeframe: str,
        horizon: int,
        direction: str,
        evaluations: Sequence[SignalEvaluationRecord],
    ) -> DirectionalPerformanceSummary:
        rows = [
            evaluation
            for evaluation in evaluations
            if evaluation.symbol == symbol
            and evaluation.timeframe == timeframe
            and evaluation.horizon_candles == horizon
            and evaluation.direction == direction
        ]
        if not rows:
            return DirectionalPerformanceSummary(
                symbol=symbol,
                timeframe=timeframe,
                horizon=horizon,
                direction=direction,
                total_signals=0,
                winrate=0.0,
                average_return=0.0,
            )

        wins = sum(1 for row in rows if row.is_positive)
        avg_return = sum(row.close_return for row in rows) / len(rows)
        return DirectionalPerformanceSummary(
            symbol=symbol,
            timeframe=timeframe,
            horizon=horizon,
            direction=direction,
            total_signals=len(rows),
            winrate=round((wins / len(rows)) * 100, 2),
            average_return=round(avg_return, 6),
        )

    def _build_threshold_summary(
        self,
        *,
        symbol: str,
        timeframe: str,
        horizon: int,
        threshold: float,
        evaluations: Sequence[SignalEvaluationRecord],
    ) -> ThresholdOptimizationSummary:
        rows = [
            evaluation
            for evaluation in evaluations
            if evaluation.symbol == symbol
            and evaluation.timeframe == timeframe
            and evaluation.horizon_candles == horizon
        ]
        if not rows:
            return ThresholdOptimizationSummary(
                symbol=symbol,
                timeframe=timeframe,
                horizon=horizon,
                threshold=threshold,
                total_signals=0,
                winrate=0.0,
                average_return=0.0,
            )

        wins = sum(1 for row in rows if row.is_positive)
        average_return = sum(row.close_return for row in rows) / len(rows)
        return ThresholdOptimizationSummary(
            symbol=symbol,
            timeframe=timeframe,
            horizon=horizon,
            threshold=threshold,
            total_signals=len(rows),
            winrate=round((wins / len(rows)) * 100, 2),
            average_return=round(average_return, 6),
        )

    def _collect_signal_evaluations(
        self,
        *,
        delta_agent: DeltaAgent,
        symbol: str,
        timeframe: str,
        horizons: Sequence[int],
    ) -> tuple[int, list[SignalEvaluationRecord], int]:
        candles = self._database.get_candles(symbol=symbol, timeframe=timeframe)
        signals = [signal for signal in delta_agent.get_historical_signals(symbol, timeframe) if signal.signal]
        candle_index = {candle.open_time: index for index, candle in enumerate(candles)}

        evaluations: list[SignalEvaluationRecord] = []
        skipped_incomplete = 0

        for signal in signals:
            entry_index = candle_index.get(signal.open_time)
            if entry_index is None:
                continue
            for horizon in horizons:
                future_candles = candles[entry_index + 1 : entry_index + 1 + horizon]
                if len(future_candles) < horizon:
                    skipped_incomplete += 1
                    continue
                evaluations.append(self._evaluate_signal(signal=signal, future_candles=future_candles, horizon=horizon))

        return len(signals), evaluations, skipped_incomplete

    @staticmethod
    def _percent_return(entry_price: float, price: float) -> float:
        if entry_price == 0:
            return 0.0
        return ((price - entry_price) / entry_price) * 100

    @staticmethod
    def _directional_return(entry_price: float, price: float, direction: str) -> float:
        if entry_price == 0:
            return 0.0
        if direction == "SHORT":
            return ((entry_price - price) / entry_price) * 100
        return ((price - entry_price) / entry_price) * 100
