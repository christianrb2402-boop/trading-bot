from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import time
from typing import Sequence

from agents.trading_brain_orchestrator import TradingBrainOrchestrator
from config.settings import Settings
from core.database import Database, RiskEventRecord


@dataclass(slots=True, frozen=True)
class MarketWatchResult:
    loops_completed: int
    observations_recorded: int


class MarketWatchEngine:
    def __init__(self, *, database: Database, settings: Settings, trading_brain: TradingBrainOrchestrator) -> None:
        self._database = database
        self._settings = settings
        self._trading_brain = trading_brain

    def run(
        self,
        *,
        symbols: Sequence[str],
        timeframes: Sequence[str],
        run_minutes: int | None,
        max_loops: int | None,
        prefer_fallback: bool,
        allow_stale_fallback: bool,
    ) -> MarketWatchResult:
        deadline = datetime.now(timezone.utc) + timedelta(minutes=run_minutes or 5)
        fast_validation_mode = max_loops is not None or (run_minutes or 0) <= 5
        target_loops = max_loops if max_loops is not None else (max(1, run_minutes or 5) if fast_validation_mode else None)
        active_timeframes = self._select_execution_timeframes(timeframes=timeframes, run_minutes=run_minutes, max_loops=max_loops)
        loops = 0
        observations = 0
        while datetime.now(timezone.utc) < deadline:
            loops += 1
            for timeframe in active_timeframes:
                for symbol in symbols:
                    decision = self._trading_brain.decide_for_symbol(
                        symbol=symbol,
                        timeframe=timeframe,
                        prefer_fallback=prefer_fallback,
                        allow_stale_fallback=allow_stale_fallback,
                        observer_mode=True,
                        operating_horizon_minutes=run_minutes or (5 if max_loops is not None else None),
                    )
                    event_type = "OPPORTUNITY_OBSERVED"
                    reason = decision.entry_reason
                    if decision.final_decision == "NO_TRADE":
                        rejection = decision.rejection_reason.lower()
                        if "cost" in rejection:
                            event_type = "COST_BLOCKED"
                        elif "stale" in rejection or "gap" in rejection or "quality" in rejection:
                            event_type = "BAD_DATA_BLOCKED"
                        else:
                            event_type = "LOW_EDGE"
                        reason = decision.rejection_reason
                    self._database.insert_risk_event(
                        RiskEventRecord(
                            timestamp=datetime.now(timezone.utc).isoformat(),
                            event_type=event_type,
                            severity="INFO",
                            symbol=symbol,
                            reason=reason,
                            action_taken="OBSERVE_ONLY",
                            raw_payload=json.dumps(decision.as_dict(), ensure_ascii=True),
                        )
                    )
                    observations += 1
            if target_loops is not None and loops >= target_loops:
                break
            if not fast_validation_mode:
                time.sleep(self._settings.market_watch_loop_seconds)
        return MarketWatchResult(loops_completed=loops, observations_recorded=observations)

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
