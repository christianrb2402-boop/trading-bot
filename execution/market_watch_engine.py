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

    def run(self, *, symbols: Sequence[str], timeframes: Sequence[str], run_minutes: int, prefer_fallback: bool, allow_stale_fallback: bool) -> MarketWatchResult:
        deadline = datetime.now(timezone.utc) + timedelta(minutes=run_minutes)
        fast_validation_mode = run_minutes <= 5
        target_loops = max(1, run_minutes) if fast_validation_mode else None
        loops = 0
        observations = 0
        while datetime.now(timezone.utc) < deadline:
            loops += 1
            for timeframe in timeframes:
                for symbol in symbols:
                    decision = self._trading_brain.decide_for_symbol(
                        symbol=symbol,
                        timeframe=timeframe,
                        prefer_fallback=prefer_fallback,
                        allow_stale_fallback=allow_stale_fallback,
                        observer_mode=True,
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
