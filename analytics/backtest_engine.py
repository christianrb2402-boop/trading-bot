from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import logging
from typing import Sequence

from agents.delta_agent import DeltaAgent
from agents.market_context_agent import MarketContextAgent
from analytics.performance_analyzer import PerformanceAnalyzer
from core.database import (
    AgentDecisionRecord,
    Database,
    ErrorEventRecord,
    MarketContextRecord,
    RejectedSignalRecord,
    SignalLogRecord,
    StoredCandle,
)
from execution.simulated_trade_tracker import SimulatedTradeTracker


logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class BacktestEvent:
    close_time: str
    symbol: str
    timeframe: str
    candle_index: int


@dataclass(slots=True, frozen=True)
class DataQualitySummary:
    symbol: str
    timeframe: str
    valid_candles: int
    duplicates: int
    gaps: int
    corrupted: int

    def as_dict(self) -> dict[str, str | int]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "valid_candles": self.valid_candles,
            "duplicates": self.duplicates,
            "gaps": self.gaps,
            "corrupted": self.corrupted,
        }


class BacktestEngine:
    _RELAXATION_SCHEDULE: tuple[float, ...] = (1.0, 0.75, 0.5, 0.3, 0.15, 0.08, 0.04)

    def __init__(
        self,
        *,
        database: Database,
        delta_agent: DeltaAgent,
        market_context_agent: MarketContextAgent,
        simulated_trade_tracker: SimulatedTradeTracker,
        performance_analyzer: PerformanceAnalyzer,
    ) -> None:
        self._database = database
        self._delta_agent = delta_agent
        self._market_context_agent = market_context_agent
        self._simulated_trade_tracker = simulated_trade_tracker
        self._performance_analyzer = performance_analyzer

    def run(
        self,
        *,
        symbols: Sequence[str],
        timeframes: Sequence[str],
        limit: int,
        min_trades: int,
    ) -> dict[str, object]:
        final_result: dict[str, object] | None = None

        for relaxation_factor in self._RELAXATION_SCHEDULE:
            self._database.reset_backtest_state()
            candles_by_key, quality_summaries = self._load_candles(
                symbols=symbols,
                timeframes=timeframes,
                limit=limit,
            )
            events = self._build_events(candles_by_key)
            attempt_result = self._run_attempt(
                candles_by_key=candles_by_key,
                events=events,
                relaxation_factor=relaxation_factor,
                quality_summaries=quality_summaries,
                min_trades=min_trades,
            )
            final_result = attempt_result
            if int(attempt_result["trade_metrics"]["closed_trades"]) >= min_trades:
                break

        if final_result is None:
            final_result = {
                "events": 0,
                "decisions": 0,
                "trades_opened": 0,
                "trades_closed": 0,
                "trade_metrics": self._database.get_simulated_trade_metrics(),
                "performance_report": self._performance_analyzer.refresh(),
                "quality_summaries": [],
                "relaxation_factor": 1.0,
                "min_trades_reached": False,
                "timeframes": list(timeframes),
            }
        return final_result

    def _run_attempt(
        self,
        *,
        candles_by_key: dict[tuple[str, str], list[StoredCandle]],
        events: list[BacktestEvent],
        relaxation_factor: float,
        quality_summaries: Sequence[DataQualitySummary],
        min_trades: int,
    ) -> dict[str, object]:
        trades_opened = 0
        trades_closed = 0
        decisions = 0

        logger.info(
            "Backtest started",
            extra={
                "event": "backtest_start",
                "context": {
                    "symbols": sorted({key[0] for key in candles_by_key}),
                    "timeframes": sorted({key[1] for key in candles_by_key}),
                    "events": len(events),
                    "relaxation_factor": relaxation_factor,
                },
            },
        )

        for event in events:
            key = (event.symbol, event.timeframe)
            symbol_candles = candles_by_key[key]
            window = symbol_candles[: event.candle_index + 1]
            recent_window = window[-20:]
            current_candle = window[-1]
            market_context = self._market_context_agent.evaluate(
                symbol=event.symbol,
                timeframe=event.timeframe,
                candles=recent_window,
            )
            self._database.insert_market_context(
                MarketContextRecord(
                    timestamp=current_candle.close_time,
                    source="BacktestMarketContextAgent",
                    macro_regime=str(market_context["macro_regime"]),
                    risk_regime=str(market_context["risk_regime"]),
                    context_score=float(market_context["context_score"]),
                    reason=str(market_context["reason"]),
                    raw_payload=json.dumps(market_context, ensure_ascii=True),
                )
            )

            signal = self._delta_agent.evaluate_from_candles(
                symbol=event.symbol,
                timeframe=event.timeframe,
                candles=recent_window,
                market_context=market_context,
                relaxation_factor=relaxation_factor,
            )
            signal_id = self._database.insert_signal_log(
                SignalLogRecord(
                    symbol=event.symbol,
                    timeframe=event.timeframe,
                    signal=str(signal["signal_type"]),
                    signal_tier=str(signal["signal_tier"]),
                    k_value=float(signal["k_value"]),
                    confidence=float(signal["confidence"]),
                    timestamp=str(signal["timestamp"]),
                )
            )

            if str(signal["signal_type"]) == "NONE":
                self._log_rejected_signal(signal=signal, rejection_reason=str(signal["reason"]))

            trade_result = self._simulated_trade_tracker.process_cycle(
                symbol=event.symbol,
                timeframe=event.timeframe,
                signal=signal,
                latest_candle=current_candle,
                signal_id=signal_id,
                current_time=current_candle.close_time,
                enable_wall_clock_expiry=False,
            )
            trades_opened += 1 if trade_result.opened else 0
            trades_closed += 1 if trade_result.closed else 0

            if str(signal["signal_type"]) in {"LONG", "SHORT"} and not trade_result.opened and trade_result.active_trade_id is not None:
                self._log_rejected_signal(signal=signal, rejection_reason="existing_open_trade")

            linked_trade_id = trade_result.opened_trade_id or trade_result.active_trade_id or trade_result.closed_trade_id
            self._database.insert_agent_decision(
                AgentDecisionRecord(
                    timestamp=current_candle.close_time,
                    agent_name="DeltaAgent",
                    symbol=event.symbol,
                    timeframe=event.timeframe,
                    decision=str(signal["signal_type"]),
                    confidence=float(signal["confidence"]),
                    inputs_used=json.dumps(
                        {
                            "k_value": signal["k_value"],
                            "signal_strength": signal["signal_strength"],
                            "signal_tier": signal["signal_tier"],
                            "roc_price": signal["roc_price"],
                            "roc_volume": signal["roc_volume"],
                            "price": signal["price"],
                            "volume": signal["volume"],
                            "trend_direction": signal["trend_direction"],
                            "volatility_regime": signal["volatility_regime"],
                            "momentum_strength": signal["momentum_strength"],
                            "volume_regime": signal["volume_regime"],
                            "market_regime": signal["market_regime"],
                            "setup_signature": signal["setup_signature"],
                            "thresholds_failed": list(signal["thresholds_failed"]),
                        },
                        ensure_ascii=True,
                    ),
                    reasoning_summary=str(signal["explanation"]),
                    linked_signal_id=signal_id,
                    linked_trade_id=linked_trade_id,
                )
            )
            decisions += 1

            if (
                str(signal["signal_type"]) != "NONE"
                or trade_result.opened
                or trade_result.closed
                or event.candle_index % 500 == 0
            ):
                logger.info(
                    "Backtest candle processed",
                    extra={
                        "event": "backtest_step",
                        "context": {
                            "symbol": event.symbol,
                            "timeframe": event.timeframe,
                            "close_time": current_candle.close_time,
                            "signal_type": signal["signal_type"],
                            "signal_tier": signal["signal_tier"],
                            "confidence": signal["confidence"],
                            "trend_direction": signal["trend_direction"],
                            "volatility_regime": signal["volatility_regime"],
                            "volume_regime": signal["volume_regime"],
                            "trade_opened": trade_result.opened,
                            "trade_closed": trade_result.closed,
                            "relaxation_factor": relaxation_factor,
                        },
                    },
                )

        for (symbol, timeframe), candles in candles_by_key.items():
            if not candles:
                continue
            closed_trade_id = self._simulated_trade_tracker.finalize_open_trade(
                symbol=symbol,
                timeframe=timeframe,
                latest_candle=candles[-1],
            )
            trades_closed += 1 if closed_trade_id is not None else 0

        performance_report = self._performance_analyzer.refresh()
        trade_metrics = self._database.get_simulated_trade_metrics()
        min_trades_reached = int(trade_metrics["closed_trades"]) >= min_trades

        logger.info(
            "Backtest completed",
            extra={
                "event": "backtest_complete",
                "context": {
                    "events": len(events),
                    "decisions": decisions,
                    "trades_opened": trades_opened,
                    "trades_closed": trades_closed,
                    "closed_trades": trade_metrics["closed_trades"],
                    "winrate": trade_metrics["winrate"],
                    "total_pnl": trade_metrics["total_pnl"],
                    "relaxation_factor": relaxation_factor,
                    "min_trades_reached": min_trades_reached,
                },
            },
        )

        return {
            "events": len(events),
            "decisions": decisions,
            "trades_opened": trades_opened,
            "trades_closed": trades_closed,
            "trade_metrics": trade_metrics,
            "performance_report": performance_report,
            "quality_summaries": [summary.as_dict() for summary in quality_summaries],
            "relaxation_factor": relaxation_factor,
            "min_trades_reached": min_trades_reached,
            "timeframes": sorted({key[1] for key in candles_by_key}),
        }

    def _load_candles(
        self,
        *,
        symbols: Sequence[str],
        timeframes: Sequence[str],
        limit: int,
    ) -> tuple[dict[tuple[str, str], list[StoredCandle]], list[DataQualitySummary]]:
        candles_by_key: dict[tuple[str, str], list[StoredCandle]] = {}
        quality_summaries: list[DataQualitySummary] = []

        for symbol in symbols:
            base_candles = self._database.get_candles(symbol=symbol, timeframe="1m")
            if limit > 0:
                base_candles = base_candles[-limit:]

            if not base_candles:
                self._persist_quality_issue(
                    symbol=symbol,
                    timeframe="1m",
                    issue_type="MISSING_DATASET",
                    issue_message="No candles available for requested symbol",
                )
                continue

            for timeframe in timeframes:
                candles = self._materialize_timeframe(base_candles=base_candles, symbol=symbol, timeframe=timeframe)
                valid_candles, summary = self._sanitize_candles(symbol=symbol, timeframe=timeframe, candles=candles)
                if valid_candles:
                    candles_by_key[(symbol, timeframe)] = valid_candles
                quality_summaries.append(summary)
        return candles_by_key, quality_summaries

    @staticmethod
    def _build_events(candles_by_key: dict[tuple[str, str], list[StoredCandle]]) -> list[BacktestEvent]:
        events: list[BacktestEvent] = []
        for (symbol, timeframe), candles in candles_by_key.items():
            for index in range(4, len(candles)):
                events.append(
                    BacktestEvent(
                        close_time=candles[index].close_time,
                        symbol=symbol,
                        timeframe=timeframe,
                        candle_index=index,
                    )
                )
        return sorted(events, key=lambda item: (item.close_time, item.timeframe, item.symbol))

    def _sanitize_candles(
        self,
        *,
        symbol: str,
        timeframe: str,
        candles: Sequence[StoredCandle],
    ) -> tuple[list[StoredCandle], DataQualitySummary]:
        valid_candles: list[StoredCandle] = []
        seen_open_times: set[str] = set()
        duplicates = 0
        gaps = 0
        corrupted = 0
        expected_delta = timedelta(seconds=self._timeframe_seconds(timeframe))

        for candle in candles:
            if candle.open_time in seen_open_times:
                duplicates += 1
                self._persist_quality_issue(
                    symbol=symbol,
                    timeframe=timeframe,
                    issue_type="DUPLICATE_CANDLE",
                    issue_message=f"Duplicate candle detected at {candle.open_time}",
                )
                continue

            if self._is_corrupted(candle):
                corrupted += 1
                self._persist_quality_issue(
                    symbol=symbol,
                    timeframe=timeframe,
                    issue_type="CORRUPTED_CANDLE",
                    issue_message=f"Corrupted candle skipped at {candle.open_time}",
                )
                continue

            if valid_candles:
                previous_open_time = datetime.fromisoformat(valid_candles[-1].open_time)
                current_open_time = datetime.fromisoformat(candle.open_time)
                if current_open_time - previous_open_time > expected_delta:
                    gaps += 1
                    self._persist_quality_issue(
                        symbol=symbol,
                        timeframe=timeframe,
                        issue_type="TIME_GAP",
                        issue_message=(
                            f"Missing candles between {valid_candles[-1].open_time} and {candle.open_time}"
                        ),
                    )

            seen_open_times.add(candle.open_time)
            valid_candles.append(candle)

        summary = DataQualitySummary(
            symbol=symbol,
            timeframe=timeframe,
            valid_candles=len(valid_candles),
            duplicates=duplicates,
            gaps=gaps,
            corrupted=corrupted,
        )
        logger.info(
            "Backtest data quality evaluated",
            extra={
                "event": "data_quality",
                "context": summary.as_dict(),
            },
        )
        return valid_candles, summary

    def _persist_quality_issue(
        self,
        *,
        symbol: str,
        timeframe: str,
        issue_type: str,
        issue_message: str,
    ) -> None:
        self._database.insert_error_event(
            ErrorEventRecord(
                timestamp=datetime.now(timezone.utc).isoformat(),
                component="data_quality",
                symbol=f"{symbol}:{timeframe}",
                error_type=issue_type,
                error_message=issue_message,
                recoverable=True,
            )
        )
        logger.warning(
            "Data quality anomaly detected",
            extra={
                "event": "data_quality_anomaly",
                "context": {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "issue_type": issue_type,
                    "issue_message": issue_message,
                },
            },
        )

    def _log_rejected_signal(self, *, signal: dict[str, object], rejection_reason: str) -> None:
        self._database.insert_rejected_signal(
            RejectedSignalRecord(
                symbol=str(signal["symbol"]),
                timeframe=str(signal["timeframe"]),
                signal_tier=str(signal["signal_tier"]),
                reason=rejection_reason,
                context_payload=json.dumps(
                    {
                        "direction": signal["direction"],
                        "k_value": signal["k_value"],
                        "confidence": signal["confidence"],
                        "trend_direction": signal["trend_direction"],
                        "volatility_regime": signal["volatility_regime"],
                        "momentum_strength": signal["momentum_strength"],
                        "volume_regime": signal["volume_regime"],
                        "market_regime": signal["market_regime"],
                        "setup_signature": signal["setup_signature"],
                    },
                    ensure_ascii=True,
                ),
                thresholds_failed=json.dumps(list(signal["thresholds_failed"]), ensure_ascii=True),
                timestamp=str(signal["timestamp"]),
            )
        )

    def _materialize_timeframe(
        self,
        *,
        base_candles: Sequence[StoredCandle],
        symbol: str,
        timeframe: str,
    ) -> list[StoredCandle]:
        if timeframe == "1m":
            return list(base_candles)

        minutes = self._timeframe_minutes(timeframe)
        if minutes <= 1:
            return list(base_candles)

        buckets: list[list[StoredCandle]] = []
        current_bucket: list[StoredCandle] = []
        current_bucket_start: datetime | None = None

        for candle in base_candles:
            open_dt = datetime.fromisoformat(candle.open_time)
            bucket_start = open_dt.replace(second=0, microsecond=0) - timedelta(minutes=open_dt.minute % minutes)
            if current_bucket_start is None or bucket_start != current_bucket_start:
                if current_bucket:
                    buckets.append(current_bucket)
                current_bucket = [candle]
                current_bucket_start = bucket_start
            else:
                current_bucket.append(candle)

        if current_bucket:
            buckets.append(current_bucket)

        aggregated: list[StoredCandle] = []
        for bucket in buckets:
            first = bucket[0]
            last = bucket[-1]
            aggregated.append(
                StoredCandle(
                    symbol=symbol,
                    timeframe=timeframe,
                    open_time=first.open_time,
                    open=first.open,
                    high=max(item.high for item in bucket),
                    low=min(item.low for item in bucket),
                    close=last.close,
                    volume=sum(item.volume for item in bucket),
                    close_time=last.close_time,
                )
            )
        return aggregated

    @staticmethod
    def _is_corrupted(candle: StoredCandle) -> bool:
        if candle.open <= 0 or candle.high <= 0 or candle.low <= 0 or candle.close <= 0 or candle.volume < 0:
            return True
        if candle.high < candle.low:
            return True
        if not (candle.low <= candle.open <= candle.high):
            return True
        if not (candle.low <= candle.close <= candle.high):
            return True
        return datetime.fromisoformat(candle.close_time) <= datetime.fromisoformat(candle.open_time)

    @staticmethod
    def _timeframe_seconds(timeframe: str) -> int:
        return BacktestEngine._timeframe_minutes(timeframe) * 60

    @staticmethod
    def _timeframe_minutes(timeframe: str) -> int:
        raw = timeframe.strip().lower()
        if raw.endswith("m"):
            return max(1, int(raw[:-1]))
        if raw.endswith("h"):
            return max(1, int(raw[:-1])) * 60
        return 1
