from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import time
from typing import Sequence

from agents.execution_simulator_agent import ExecutionSimulatorAgent
from agents.trading_brain_orchestrator import TradingBrainOrchestrator
from config.settings import Settings
from core.database import Database, ErrorEventRecord
from core.ledger_reconciler import LedgerReconciler
from data.live_context_fusion import refresh_external_context


@dataclass(slots=True, frozen=True)
class AutonomousPaperResult:
    loops_completed: int
    decisions_processed: int
    trades_opened: int
    trades_closed: int
    stopped_reason: str


class AutonomousPaperEngine:
    def __init__(
        self,
        *,
        database: Database,
        settings: Settings,
        trading_brain: TradingBrainOrchestrator,
        execution_agent: ExecutionSimulatorAgent,
        ledger_reconciler: LedgerReconciler,
    ) -> None:
        self._database = database
        self._settings = settings
        self._trading_brain = trading_brain
        self._execution_agent = execution_agent
        self._ledger_reconciler = ledger_reconciler

    def run(
        self,
        *,
        symbols: Sequence[str],
        timeframes: Sequence[str],
        run_minutes: int | None,
        max_loops: int | None,
        prefer_fallback: bool,
        allow_stale_fallback: bool,
    ) -> AutonomousPaperResult:
        deadline = datetime.now(timezone.utc) + timedelta(minutes=run_minutes or 5)
        fast_validation_mode = max_loops is not None or (run_minutes or 0) <= 5
        target_loops = max_loops if max_loops is not None else (max(1, run_minutes or 5) if fast_validation_mode else None)
        active_timeframes = self._select_execution_timeframes(timeframes=timeframes, run_minutes=run_minutes, max_loops=max_loops)
        loops = 0
        decisions = 0
        opened = 0
        closed = 0
        exploration_opened_this_run = 0
        stop_reason = "completed_requested_run"
        while datetime.now(timezone.utc) < deadline:
            ledger_report = self._ledger_reconciler.inspect()
            if ledger_report.result != "OK":
                stop_reason = f"ledger_{ledger_report.result.lower()}"
                break
            refresh_external_context(
                database=self._database,
                settings=self._settings,
                symbols=symbols,
                limit=5,
            )
            for timeframe in active_timeframes:
                for symbol in symbols:
                    decision = self._trading_brain.decide_for_symbol(
                        symbol=symbol,
                        timeframe=timeframe,
                        prefer_fallback=prefer_fallback,
                        allow_stale_fallback=allow_stale_fallback,
                        observer_mode=False,
                        operating_horizon_minutes=run_minutes or (5 if max_loops is not None else None),
                    )
                    decisions += 1
                    if decision.data_stale and not allow_stale_fallback:
                        stop_reason = "stale_data_detected"
                        break
                    latest_candle = self._database.get_recent_candles(symbol=symbol, timeframe=timeframe, limit=1)
                    if not latest_candle:
                        continue
                    signal = {
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "signal_type": decision.final_decision if decision.final_decision in {"LONG", "SHORT"} else "NONE",
                        "decision_type": decision.final_decision,
                        "direction": decision.final_decision if decision.final_decision in {"LONG", "SHORT"} else "NONE",
                        "signal_strength": decision.final_score,
                        "confidence": decision.confidence,
                        "price": latest_candle[-1].close,
                        "trend_direction": decision.raw_payload.get("market_context", {}).get("trend_direction", "SIDEWAYS"),
                        "volatility_regime": decision.raw_payload.get("market_state", {}).get("volatility_state", "LOW"),
                        "momentum_strength": decision.raw_payload.get("market_context", {}).get("momentum_strength", 0.0),
                        "volume_regime": decision.raw_payload.get("market_state", {}).get("volume_state", "NORMAL"),
                        "market_regime": decision.raw_payload.get("market_context", {}).get("market_regime", "RANGING"),
                        "setup_signature": decision.selected_strategy,
                        "explanation": decision.entry_reason,
                        "provider_used": decision.provider_used,
                        "paper_mode": decision.paper_mode,
                        "risk_reward_snapshot": decision.raw_payload.get("risk_reward", {}),
                        "cost_snapshot": decision.raw_payload.get("cost_snapshot", {}),
                        "agent_votes": decision.raw_payload.get("strategy_votes", []),
                        "position_size_usd": decision.raw_payload.get("position_size_usd", 0.0),
                    }
                    if (
                        decision.paper_mode == "PAPER_EXPLORATION"
                        and decision.final_decision in {"LONG", "SHORT"}
                        and exploration_opened_this_run >= self._settings.exploration_max_trades_per_short_run
                    ):
                        signal["signal_type"] = "NONE"
                        signal["decision_type"] = "NO_TRADE"
                        signal["direction"] = "NONE"
                        signal["explanation"] = "short run exploration cap reached"
                    result = self._execution_agent.process_cycle(
                        symbol=symbol,
                        timeframe=timeframe,
                        signal=signal,
                        latest_candle=latest_candle[-1],
                        signal_id=None,
                        current_time=latest_candle[-1].close_time,
                        provider_used=decision.provider_used,
                    )
                    opened += int(result.cycle_result.opened)
                    closed += int(result.cycle_result.closed)
                    if decision.paper_mode == "PAPER_EXPLORATION" and result.cycle_result.opened:
                        exploration_opened_this_run += 1
                if stop_reason != "completed_requested_run":
                    break
            loops += 1
            if stop_reason != "completed_requested_run":
                break
            if target_loops is not None and loops >= target_loops:
                break
            if not fast_validation_mode:
                time.sleep(self._settings.autonomous_loop_seconds)

        if stop_reason != "completed_requested_run":
            self._database.insert_error_event(
                ErrorEventRecord(
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    component="autonomous_paper_engine",
                    symbol=None,
                    error_type="AUTONOMOUS_KILLSWITCH",
                    error_message=stop_reason,
                    recoverable=True,
                )
            )
        return AutonomousPaperResult(
            loops_completed=loops,
            decisions_processed=decisions,
            trades_opened=opened,
            trades_closed=closed,
            stopped_reason=stop_reason,
        )

    def _select_execution_timeframes(
        self,
        *,
        timeframes: Sequence[str],
        run_minutes: int | None,
        max_loops: int | None,
    ) -> tuple[str, ...]:
        if (run_minutes is not None and run_minutes <= 60) or max_loops is not None:
            filtered = tuple(timeframe for timeframe in timeframes if timeframe in self._settings.execution_timeframes)
            return filtered or tuple(self._settings.execution_timeframes)
        return tuple(timeframes)
