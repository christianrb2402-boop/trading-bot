from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import logging
import time
from typing import Any, Sequence

from agents.cost_model_agent import CostModelAgent
from agents.execution_simulator_agent import ExecutionSimulatorAgent
from agents.market_context_agent import MarketContextAgent
from agents.market_data_agent import MarketDataAgent
from agents.net_profitability_gate import NetProfitabilityGate
from config.settings import Settings
from core.database import (
    AgentDecisionRecord,
    Database,
    ErrorEventRecord,
    MarketContextRecord,
    MarketSnapshotRecord,
    PaperPortfolioRecord,
    ProviderStatusRecord,
    RejectedSignalRecord,
    SignalLogRecord,
    SimulatedTradeRecord,
    StoredCandle,
)
from core.exceptions import ExternalServiceError
from core.ledger_reconciler import LedgerReconciler
from data.binance_market_data import BinanceConnectivityProbe, BinanceMarketDataService, Candle


logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class IntradayCoreEngineResult:
    loops_completed: int
    trades_opened: int
    trades_closed: int
    provider_live_binance: bool
    fresh_data_ok: bool
    stopped_reason: str
    rejection_counts: dict[str, int]


class IntradayCoreEngine:
    def __init__(
        self,
        *,
        database: Database,
        settings: Settings,
        service: BinanceMarketDataService,
        market_data_agent: MarketDataAgent,
        market_context_agent: MarketContextAgent,
        cost_model_agent: CostModelAgent,
        net_profitability_gate: NetProfitabilityGate,
        execution_agent: ExecutionSimulatorAgent,
        ledger_reconciler: LedgerReconciler,
    ) -> None:
        self._database = database
        self._settings = settings
        self._service = service
        self._market_data_agent = market_data_agent
        self._market_context_agent = market_context_agent
        self._cost_model_agent = cost_model_agent
        self._net_profitability_gate = net_profitability_gate
        self._execution_agent = execution_agent
        self._ledger_reconciler = ledger_reconciler
        self._mode_name = settings.intraday_core_mode_name

    def run(
        self,
        *,
        symbols: Sequence[str],
        max_loops: int | None,
        run_minutes: int | None,
    ) -> IntradayCoreEngineResult:
        loops_completed = 0
        trades_opened = 0
        trades_closed = 0
        rejection_counts: dict[str, int] = defaultdict(int)
        self._ensure_portfolio_initialized()

        probes = self._service.diagnose_connectivity()
        provider_live_binance = self._binance_http_usable(probes)
        self._persist_provider_probe_status(probes=probes, provider_live_binance=provider_live_binance)
        if not provider_live_binance:
            return IntradayCoreEngineResult(
                loops_completed=0,
                trades_opened=0,
                trades_closed=0,
                provider_live_binance=False,
                fresh_data_ok=False,
                stopped_reason="binance_http_unavailable",
                rejection_counts={},
            )

        ledger_report = self._ledger_reconciler.inspect()
        if ledger_report.result != "OK":
            return IntradayCoreEngineResult(
                loops_completed=0,
                trades_opened=0,
                trades_closed=0,
                provider_live_binance=True,
                fresh_data_ok=False,
                stopped_reason=f"ledger_{ledger_report.result.lower()}",
                rejection_counts={},
            )

        deadline = datetime.now(timezone.utc) + timedelta(minutes=run_minutes or 5)
        stopped_reason = "completed_requested_run"
        fresh_data_ok = True
        while datetime.now(timezone.utc) < deadline:
            loops_completed += 1
            loop_timestamp = datetime.now(timezone.utc).isoformat()
            short_run_trade_cap_hit = max_loops is not None and trades_opened >= self._settings.intraday_core_max_trades_per_short_run
            if short_run_trade_cap_hit:
                stopped_reason = "short_run_trade_cap_reached"
                break

            for symbol in symbols:
                symbol_result = self._process_symbol(symbol=symbol, timestamp=loop_timestamp, trade_cap_remaining=max(0, self._settings.intraday_core_max_trades_per_short_run - trades_opened))
                trades_opened += symbol_result["opened"]
                trades_closed += symbol_result["closed"]
                fresh_data_ok = fresh_data_ok and bool(symbol_result["fresh_data_ok"])
                for reason, count in symbol_result["rejection_counts"].items():
                    rejection_counts[reason] += count
                if symbol_result["stop_engine"]:
                    stopped_reason = str(symbol_result["stop_reason"])
                    break
            self._update_portfolio_snapshot(timestamp=loop_timestamp)

            if stopped_reason != "completed_requested_run":
                break
            if max_loops is not None and loops_completed >= max_loops:
                break
            if max_loops is None:
                time.sleep(self._settings.autonomous_loop_seconds)

        return IntradayCoreEngineResult(
            loops_completed=loops_completed,
            trades_opened=trades_opened,
            trades_closed=trades_closed,
            provider_live_binance=provider_live_binance,
            fresh_data_ok=fresh_data_ok,
            stopped_reason=stopped_reason,
            rejection_counts=dict(rejection_counts),
        )

    def _process_symbol(self, *, symbol: str, timestamp: str, trade_cap_remaining: int) -> dict[str, Any]:
        rejection_counts: dict[str, int] = defaultdict(int)
        candle_map: dict[str, list[Candle]] = {}
        required_timeframes = (
            *self._settings.intraday_core_execution_timeframes,
            self._settings.intraday_core_confirmation_timeframe,
            *self._settings.intraday_core_soft_context_timeframes,
        )
        required_timeframes = tuple(dict.fromkeys(required_timeframes))

        for timeframe in required_timeframes:
            try:
                candles = self._service.fetch_latest_closed_candles(
                    symbol=symbol,
                    timeframe=timeframe,
                    limit=max(40, self._settings.binance_klines_limit),
                )
            except ExternalServiceError as exc:
                self._persist_provider_error(symbol=symbol, timeframe=timeframe, error=exc)
                rejection_counts["provider_not_binance"] += 1
                return {
                    "opened": 0,
                    "closed": 0,
                    "fresh_data_ok": False,
                    "rejection_counts": rejection_counts,
                    "stop_engine": True,
                    "stop_reason": "binance_fetch_failed",
                }
            candle_map[timeframe] = candles
            if candles:
                self._database.insert_candles(candles)
            assessment = self._market_data_agent.assess(
                symbol=symbol,
                timeframe=timeframe,
                candles=candles,
                provider_used="BINANCE",
            )
            latest = candles[-1] if candles else None
            self._database.insert_market_snapshot(
                MarketSnapshotRecord(
                    timestamp=latest.close_time if latest else timestamp,
                    symbol=symbol,
                    timeframe=timeframe,
                    provider_used="BINANCE",
                    open_price=latest.open if latest else 0.0,
                    high_price=latest.high if latest else 0.0,
                    low_price=latest.low if latest else 0.0,
                    close_price=latest.close if latest else 0.0,
                    volume=latest.volume if latest else 0.0,
                    is_valid=assessment.is_valid,
                    is_stale=assessment.is_stale,
                    notes="; ".join(assessment.notes),
                )
            )
            if timeframe in (*self._settings.intraday_core_execution_timeframes, self._settings.intraday_core_confirmation_timeframe):
                if not assessment.is_valid or assessment.is_stale:
                    reason = "stale_data" if assessment.is_stale else "poor_data_quality"
                    rejection_counts[reason] += 1
                    self._persist_simple_rejection(
                        symbol=symbol,
                        timeframe=timeframe,
                        timestamp=timestamp,
                        simple_reasons=[reason],
                        reason_text="BINANCE live candles are not fresh enough for intraday core execution",
                        market_regime="UNKNOWN",
                    )
                    return {
                        "opened": 0,
                        "closed": 0,
                        "fresh_data_ok": False,
                        "rejection_counts": rejection_counts,
                        "stop_engine": False,
                        "stop_reason": "",
                    }

        closed_updates = self._update_open_trades(symbol=symbol, candle_map=candle_map)

        global_open_positions = len(self._database.get_open_paper_positions())
        open_symbol_trades = [
            trade for trade in self._database.get_open_simulated_trades()
            if trade.symbol == symbol and trade.paper_mode == self._mode_name
        ]
        if global_open_positions >= self._settings.intraday_core_max_open_positions:
            rejection_counts["risk_limits_exceeded"] += 1
            self._persist_simple_rejection(
                symbol=symbol,
                timeframe=self._settings.intraday_core_execution_timeframes[-1],
                timestamp=timestamp,
                simple_reasons=["risk_limits_exceeded"],
                reason_text="Intraday core risk limits reached max open positions",
                market_regime="UNKNOWN",
            )
            return {
                "opened": 0,
                "closed": closed_updates,
                "fresh_data_ok": True,
                "rejection_counts": rejection_counts,
                "stop_engine": False,
                "stop_reason": "",
            }
        if len(open_symbol_trades) >= self._settings.intraday_core_max_open_positions_per_symbol:
            rejection_counts["symbol_open_trade_exists"] += 1
            self._persist_simple_rejection(
                symbol=symbol,
                timeframe=self._settings.intraday_core_execution_timeframes[-1],
                timestamp=timestamp,
                simple_reasons=["symbol_open_trade_exists"],
                reason_text="Intraday core already has an open trade for this symbol",
                market_regime="UNKNOWN",
            )
            return {
                "opened": 0,
                "closed": closed_updates,
                "fresh_data_ok": True,
                "rejection_counts": rejection_counts,
                "stop_engine": False,
                "stop_reason": "",
            }
        if self._symbol_is_on_cooldown(symbol=symbol, reference_time=timestamp):
            rejection_counts["symbol_cooldown_after_loss"] += 1
            self._persist_simple_rejection(
                symbol=symbol,
                timeframe=self._settings.intraday_core_execution_timeframes[-1],
                timestamp=timestamp,
                simple_reasons=["symbol_cooldown_after_loss"],
                reason_text="Intraday core symbol is still cooling down after a recent loss",
                market_regime="UNKNOWN",
            )
            return {
                "opened": 0,
                "closed": closed_updates,
                "fresh_data_ok": True,
                "rejection_counts": rejection_counts,
                "stop_engine": False,
                "stop_reason": "",
            }
        if trade_cap_remaining <= 0:
            rejection_counts["trade_cap_reached"] += 1
            return {
                "opened": 0,
                "closed": closed_updates,
                "fresh_data_ok": True,
                "rejection_counts": rejection_counts,
                "stop_engine": False,
                "stop_reason": "",
            }

        setup = self._build_setup(symbol=symbol, candle_map=candle_map, timestamp=timestamp)
        if not setup["approved"]:
            for reason in setup["simple_reasons"]:
                rejection_counts[str(reason)] += 1
            self._persist_simple_rejection(
                symbol=symbol,
                timeframe=str(setup["timeframe"]),
                timestamp=timestamp,
                simple_reasons=list(setup["simple_reasons"]),
                reason_text=str(setup["reason"]),
                market_regime=str(setup["market_regime"]),
                payload=setup,
            )
            self._persist_core_decision(
                timestamp=timestamp,
                symbol=symbol,
                timeframe=str(setup["timeframe"]),
                decision="NO_TRADE",
                confidence=float(setup["confidence"]),
                reasoning_summary=str(setup["reason"]),
                inputs=setup,
            )
            return {
                "opened": 0,
                "closed": closed_updates,
                "fresh_data_ok": True,
                "rejection_counts": rejection_counts,
                "stop_engine": False,
                "stop_reason": "",
            }

        signal = self._build_signal_from_setup(setup=setup)
        latest_candle = candle_map[str(setup["timeframe"])][-1]
        self._database.insert_signal_log(
            SignalLogRecord(
                symbol=symbol,
                timeframe=str(setup["timeframe"]),
                signal=str(signal["signal_type"]),
                signal_tier=str(signal["signal_tier"]),
                k_value=float(signal["signal_strength"]),
                confidence=float(signal["confidence"]),
                timestamp=timestamp,
                provider_used="BINANCE",
            )
        )
        self._persist_core_decision(
            timestamp=timestamp,
            symbol=symbol,
            timeframe=str(setup["timeframe"]),
            decision=str(signal["signal_type"]),
            confidence=float(signal["confidence"]),
            reasoning_summary=str(signal["explanation"]),
            inputs=setup,
        )
        execution_result = self._execution_agent.process_cycle(
            symbol=symbol,
            timeframe=str(setup["timeframe"]),
            signal=signal,
            latest_candle=self._to_stored_candle(latest_candle),
            signal_id=None,
            current_time=timestamp,
            provider_used="BINANCE",
        )
        return {
            "opened": int(execution_result.cycle_result.opened),
            "closed": closed_updates + int(execution_result.cycle_result.closed),
            "fresh_data_ok": True,
            "rejection_counts": rejection_counts,
            "stop_engine": False,
            "stop_reason": "",
        }

    def _build_setup(self, *, symbol: str, candle_map: dict[str, list[Candle]], timestamp: str) -> dict[str, Any]:
        execution_timeframe = self._settings.intraday_core_execution_timeframes[-1]
        entry_timeframe = self._settings.intraday_core_execution_timeframes[0]
        candles_1m = candle_map.get(self._settings.intraday_core_execution_timeframes[0], [])
        candles_5m = candle_map.get(self._settings.intraday_core_execution_timeframes[-1], [])
        candles_15m = candle_map.get(self._settings.intraday_core_confirmation_timeframe, [])
        candles_30m = candle_map.get(self._settings.intraday_core_soft_context_timeframes[0], [])
        if len(candles_1m) < 25 or len(candles_5m) < 25 or len(candles_15m) < 20:
            return {
                "approved": False,
                "timeframe": execution_timeframe,
                "simple_reasons": ["poor_data_quality"],
                "reason": "Intraday core does not have enough live BINANCE candles to evaluate the setup",
                "market_regime": "UNKNOWN",
                "confidence": 0.0,
            }

        context_5m = self._market_context_agent.evaluate(
            symbol=symbol,
            timeframe=self._settings.intraday_core_execution_timeframes[-1],
            candles=[self._to_stored_candle(candle) for candle in candles_5m],
        )
        context_15m = self._market_context_agent.evaluate(
            symbol=symbol,
            timeframe=self._settings.intraday_core_confirmation_timeframe,
            candles=[self._to_stored_candle(candle) for candle in candles_15m],
        )
        context_30m = self._market_context_agent.evaluate(
            symbol=symbol,
            timeframe=self._settings.intraday_core_soft_context_timeframes[0],
            candles=[self._to_stored_candle(candle) for candle in candles_30m],
        ) if candles_30m else {
            "trend_direction": "SIDEWAYS",
            "market_regime": "RANGING",
            "context_score": 0.0,
            "reason": "No soft context candles available",
        }
        self._database.insert_market_context(
            MarketContextRecord(
                timestamp=timestamp,
                source="IntradayCoreEngine",
                macro_regime=str(context_15m.get("macro_regime", "UNKNOWN")),
                risk_regime=str(context_15m.get("risk_regime", "UNKNOWN")),
                context_score=float(context_15m.get("context_score", 0.0)),
                reason=json.dumps(
                    {
                        "context_5m": context_5m,
                        "context_15m": context_15m,
                        "context_30m": context_30m,
                    },
                    ensure_ascii=True,
                ),
                raw_payload=json.dumps(
                    {
                        "symbol": symbol,
                        "contexts": {
                            "5m": context_5m,
                            "15m": context_15m,
                            "30m": context_30m,
                        },
                    },
                    ensure_ascii=True,
                ),
                provider_used="BINANCE",
            )
        )

        closes_5m = [candle.close for candle in candles_5m]
        closes_15m = [candle.close for candle in candles_15m]
        closes_1m = [candle.close for candle in candles_1m]
        sma8_5m = self._sma(closes_5m, 8)
        sma20_5m = self._sma(closes_5m, 20)
        sma8_15m = self._sma(closes_15m, 8)
        sma10_1m = self._sma(closes_1m, 10)
        latest_5m = candles_5m[-1]
        latest_15m = candles_15m[-1]
        latest_1m = candles_1m[-1]
        trend_strength_pct = abs(((latest_5m.close - closes_5m[-6]) / closes_5m[-6]) * 100) if closes_5m[-6] else 0.0
        atr_1m = self._atr_pct(candles_1m[-15:])
        atr_5m = self._atr_pct(candles_5m[-15:])
        pullback_tolerance_multiplier = self._settings.intraday_core_pullback_tolerance_pct / 100

        trend_up_5m = (
            latest_5m.close > sma8_5m > sma20_5m
            and str(context_5m.get("trend_direction", "SIDEWAYS")) == "UP"
            and trend_strength_pct >= self._settings.intraday_core_min_trend_strength_pct
        )
        trend_down_5m = (
            latest_5m.close < sma8_5m < sma20_5m
            and str(context_5m.get("trend_direction", "SIDEWAYS")) == "DOWN"
            and trend_strength_pct >= self._settings.intraday_core_min_trend_strength_pct
        )
        confirm_up_15m = (
            str(context_15m.get("trend_direction", "SIDEWAYS")) != "DOWN"
            and latest_15m.close >= sma8_15m
        )
        confirm_down_15m = (
            str(context_15m.get("trend_direction", "SIDEWAYS")) != "UP"
            and latest_15m.close <= sma8_15m
        )
        pullback_long_1m = (
            latest_1m.close > sma10_1m
            and min(candle.low for candle in candles_1m[-5:]) <= sma10_1m * (1 + pullback_tolerance_multiplier)
            and latest_1m.close > candles_1m[-2].close
        )
        pullback_short_1m = (
            latest_1m.close < sma10_1m
            and max(candle.high for candle in candles_1m[-5:]) >= sma10_1m * (1 - pullback_tolerance_multiplier)
            and latest_1m.close < candles_1m[-2].close
        )
        pullback_long_5m = (
            latest_5m.close > sma8_5m
            and latest_5m.low <= sma8_5m * (1 + pullback_tolerance_multiplier)
            and latest_5m.close > latest_5m.open
        )
        pullback_short_5m = (
            latest_5m.close < sma8_5m
            and latest_5m.high >= sma8_5m * (1 - pullback_tolerance_multiplier)
            and latest_5m.close < latest_5m.open
        )

        direction = "NONE"
        if trend_up_5m and confirm_up_15m:
            direction = "LONG"
        elif trend_down_5m and confirm_down_15m:
            direction = "SHORT"
        elif trend_up_5m or trend_down_5m:
            return {
                "approved": False,
                "timeframe": execution_timeframe,
                "simple_reasons": ["multi_timeframe_contradiction"],
                "reason": "5m trend exists but 15m confirmation is not aligned enough for the intraday core setup",
                "market_regime": str(context_5m.get("market_regime", "UNKNOWN")),
                "confidence": 0.25,
            }
        else:
            return {
                "approved": False,
                "timeframe": execution_timeframe,
                "simple_reasons": ["signal_not_actionable"],
                "reason": "5m trend is not strong enough for TREND_PULLBACK_INTRADAY",
                "market_regime": str(context_5m.get("market_regime", "UNKNOWN")),
                "confidence": 0.2,
            }

        if direction == "LONG":
            if pullback_long_1m:
                entry_timeframe = self._settings.intraday_core_execution_timeframes[0]
                entry_candles = candles_1m
                latest_entry = latest_1m
            elif pullback_long_5m:
                entry_timeframe = self._settings.intraday_core_execution_timeframes[-1]
                entry_candles = candles_5m
                latest_entry = latest_5m
            else:
                return {
                    "approved": False,
                    "timeframe": execution_timeframe,
                    "simple_reasons": ["signal_not_actionable"],
                    "reason": "Trend and confirmation exist, but the tactical pullback entry has not formed yet",
                    "market_regime": str(context_5m.get("market_regime", "UNKNOWN")),
                    "confidence": 0.35,
                }
        else:
            if pullback_short_1m:
                entry_timeframe = self._settings.intraday_core_execution_timeframes[0]
                entry_candles = candles_1m
                latest_entry = latest_1m
            elif pullback_short_5m:
                entry_timeframe = self._settings.intraday_core_execution_timeframes[-1]
                entry_candles = candles_5m
                latest_entry = latest_5m
            else:
                return {
                    "approved": False,
                    "timeframe": execution_timeframe,
                    "simple_reasons": ["signal_not_actionable"],
                    "reason": "Trend and confirmation exist, but the tactical pullback entry has not formed yet",
                    "market_regime": str(context_5m.get("market_regime", "UNKNOWN")),
                    "confidence": 0.35,
                }

        soft_context_conflict = (
            direction == "LONG" and str(context_30m.get("trend_direction", "SIDEWAYS")) == "DOWN"
        ) or (
            direction == "SHORT" and str(context_30m.get("trend_direction", "SIDEWAYS")) == "UP"
        )
        confidence = 0.58
        if str(context_15m.get("trend_direction", "SIDEWAYS")) in {"UP", "DOWN"}:
            confidence += 0.08
        if entry_timeframe == self._settings.intraday_core_execution_timeframes[0]:
            confidence += 0.04
        if soft_context_conflict:
            confidence -= 0.05
        confidence = max(0.25, min(0.82, confidence))
        signal_tier = "STRONG" if confidence >= 0.7 else "MEDIUM" if confidence >= 0.55 else "WEAK"

        entry_price = latest_entry.close
        atr_entry = atr_1m if entry_timeframe == self._settings.intraday_core_execution_timeframes[0] else atr_5m
        stop_pct = max(0.18, min(0.75, atr_entry * 1.05 if atr_entry > 0 else 0.25))
        reward_pct = max(stop_pct * 2.0, atr_entry * 2.3 if atr_entry > 0 else 0.45, 0.45)
        swing_window = entry_candles[-6:]
        if direction == "LONG":
            swing_stop = min(candle.low for candle in swing_window) * 0.999
            hard_stop = entry_price * (1 - (stop_pct / 100))
            stop_loss_price = min(swing_stop, hard_stop)
            take_profit_price = entry_price * (1 + (reward_pct / 100))
        else:
            swing_stop = max(candle.high for candle in swing_window) * 1.001
            hard_stop = entry_price * (1 + (stop_pct / 100))
            stop_loss_price = max(swing_stop, hard_stop)
            take_profit_price = entry_price * (1 - (reward_pct / 100))

        cost_snapshot = self._cost_model_agent.estimate(
            entry_price=entry_price,
            direction=direction,
            position_size_usd=self._settings.intraday_core_position_size_usd,
            volatility_pct=max(atr_entry, atr_5m),
            market_type=self._settings.simulated_market_type,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
        )
        gate_signal = {
            "signal_type": direction,
            "volatility_pct": max(atr_entry, atr_5m),
            "probability_win": 0.56 if signal_tier == "MEDIUM" else 0.6 if signal_tier == "STRONG" else 0.52,
        }
        net_gate = self._net_profitability_gate.evaluate(
            signal=gate_signal,
            cost_snapshot=cost_snapshot,
            risk_mode="BALANCED",
            paper_mode="PAPER_EXPLORATION",
        )
        if not net_gate.approved:
            simple_reasons = self._map_net_gate_reasons(net_gate.rejection_reasons)
            if soft_context_conflict and "multi_timeframe_contradiction" not in simple_reasons:
                simple_reasons.append("multi_timeframe_contradiction")
            return {
                "approved": False,
                "timeframe": entry_timeframe,
                "simple_reasons": tuple(dict.fromkeys(simple_reasons)),
                "reason": net_gate.reason,
                "market_regime": str(context_5m.get("market_regime", "UNKNOWN")),
                "confidence": confidence,
                "expected_move_pct": net_gate.expected_move_pct,
                "expected_net_edge_pct": net_gate.expected_net_edge_pct,
                "required_break_even_move_pct": net_gate.minimum_required_move_pct,
                "cost_drag_pct": net_gate.cost_drag_pct,
                "net_gate": net_gate.as_dict(),
            }

        reason = (
            f"TREND_PULLBACK_INTRADAY {direction} approved from {entry_timeframe}: "
            f"5m trend aligned, 15m confirmation present, pullback entry detected, "
            f"expected net edge {net_gate.expected_net_edge_pct}% after costs."
        )
        if soft_context_conflict:
            reason += " 30m soft context disagrees, so confidence is reduced but not blocked."
        return {
            "approved": True,
            "symbol": symbol,
            "direction": direction,
            "timeframe": entry_timeframe,
            "signal_tier": signal_tier,
            "confidence": confidence,
            "reason": reason,
            "market_regime": str(context_5m.get("market_regime", "UNKNOWN")),
            "entry_price": entry_price,
            "stop_loss_price": stop_loss_price,
            "take_profit_price": take_profit_price,
            "expected_move_pct": net_gate.expected_move_pct,
            "expected_net_edge_pct": net_gate.expected_net_edge_pct,
            "required_break_even_move_pct": net_gate.minimum_required_move_pct,
            "cost_drag_pct": net_gate.cost_drag_pct,
            "cost_snapshot": cost_snapshot.as_dict(),
            "net_gate": net_gate.as_dict(),
            "contexts": {
                "5m": context_5m,
                "15m": context_15m,
                "30m": context_30m,
            },
            "soft_context_conflict": soft_context_conflict,
            "simple_reasons": (),
        }

    def _build_signal_from_setup(self, *, setup: dict[str, Any]) -> dict[str, Any]:
        return {
            "symbol": str(setup["symbol"]),
            "timeframe": str(setup["timeframe"]),
            "signal_type": str(setup["direction"]),
            "decision_type": "TREND_PULLBACK_INTRADAY",
            "direction": str(setup["direction"]),
            "signal_strength": float(setup["expected_move_pct"]),
            "confidence": float(setup["confidence"]),
            "price": float(setup["entry_price"]),
            "trend_direction": str(setup["contexts"]["5m"].get("trend_direction", "SIDEWAYS")),
            "volatility_regime": str(setup["contexts"]["5m"].get("volatility_regime", "NORMAL")),
            "momentum_strength": float(setup["contexts"]["5m"].get("momentum_strength", 0.0)),
            "volume_regime": str(setup["contexts"]["5m"].get("volume_regime", "NORMAL")),
            "market_regime": str(setup["market_regime"]),
            "setup_signature": "TREND_PULLBACK_INTRADAY",
            "explanation": str(setup["reason"]),
            "provider_used": "BINANCE",
            "paper_mode": self._mode_name,
            "risk_reward_snapshot": {
                "stop_loss_price": float(setup["stop_loss_price"]),
                "take_profit_price": float(setup["take_profit_price"]),
            },
            "cost_snapshot": dict(setup["cost_snapshot"]),
            "agent_votes": [
                {
                    "agent_name": "IntradayCoreEngine",
                    "vote": str(setup["direction"]),
                    "confidence": float(setup["confidence"]),
                    "reason": str(setup["reason"]),
                }
            ],
            "position_size_usd": float(self._settings.intraday_core_position_size_usd),
            "leverage_simulated": float(self._settings.simulated_default_leverage),
            "signal_tier": str(setup["signal_tier"]),
        }

    def _update_open_trades(self, *, symbol: str, candle_map: dict[str, list[Candle]]) -> int:
        closed = 0
        open_trades = [
            trade for trade in self._database.get_open_simulated_trades()
            if trade.symbol == symbol and trade.paper_mode == self._mode_name
        ]
        for trade in open_trades:
            candles = candle_map.get(trade.timeframe, [])
            if not candles:
                continue
            latest_candle = candles[-1]
            result = self._execution_agent.process_cycle(
                symbol=trade.symbol,
                timeframe=trade.timeframe,
                signal={
                    "signal_type": "NONE",
                    "decision_type": "MANAGE_OPEN_TRADE",
                    "direction": "NONE",
                    "signal_strength": 0.0,
                    "confidence": 0.0,
                    "price": latest_candle.close,
                    "provider_used": "BINANCE",
                    "paper_mode": self._mode_name,
                },
                latest_candle=self._to_stored_candle(latest_candle),
                signal_id=None,
                current_time=latest_candle.close_time,
                provider_used="BINANCE",
            )
            closed += int(result.cycle_result.closed)
        return closed

    def _symbol_is_on_cooldown(self, *, symbol: str, reference_time: str) -> bool:
        reference_dt = datetime.fromisoformat(reference_time)
        cooldown = timedelta(minutes=self._settings.intraday_core_symbol_cooldown_minutes)
        for trade in self._database.get_recent_simulated_trades(limit=200):
            if trade.symbol != symbol or trade.paper_mode != self._mode_name:
                continue
            if trade.status == "OPEN" or not trade.exit_time:
                continue
            trade_net = (
                trade.final_net_pnl_after_all_costs
                if trade.final_net_pnl_after_all_costs is not None
                else (trade.net_pnl if trade.net_pnl is not None else (trade.pnl or 0.0))
            )
            if trade_net >= 0:
                continue
            exit_dt = datetime.fromisoformat(trade.exit_time)
            if reference_dt - exit_dt <= cooldown:
                return True
        return False

    def _persist_simple_rejection(
        self,
        *,
        symbol: str,
        timeframe: str,
        timestamp: str,
        simple_reasons: list[str],
        reason_text: str,
        market_regime: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        primary_reason = simple_reasons[0] if simple_reasons else "general_rejection"
        secondary_reason = simple_reasons[1] if len(simple_reasons) > 1 else ""
        context_payload = {
            "mode": self._mode_name,
            "rejection_diagnostics": {
                "simple_reasons": simple_reasons,
                "primary_reason": primary_reason,
                "secondary_reason": secondary_reason,
            },
        }
        if payload:
            context_payload["setup"] = payload
        self._database.insert_rejected_signal(
            RejectedSignalRecord(
                symbol=symbol,
                timeframe=timeframe,
                signal_tier="REJECTED",
                reason=reason_text,
                context_payload=json.dumps(context_payload, ensure_ascii=True),
                thresholds_failed=json.dumps(simple_reasons, ensure_ascii=True),
                timestamp=timestamp,
                rejected_by_agent="IntradayCoreEngine",
                rejected_stage="INTRADAY_CORE",
                expected_move_pct=float(payload.get("expected_move_pct", 0.0) if payload else 0.0),
                total_cost_pct=float(payload.get("required_break_even_move_pct", 0.0) if payload else 0.0),
                expected_net_edge_pct=float(payload.get("expected_net_edge_pct", 0.0) if payload else 0.0),
                risk_reward_ratio=float((payload or {}).get("net_gate", {}).get("expected_net_reward_risk", 0.0)),
                cost_coverage_multiple=float((payload or {}).get("net_gate", {}).get("cost_coverage_multiple", 0.0)),
                multi_timeframe_conflict="multi_timeframe_contradiction" in simple_reasons,
                market_regime=market_regime,
                selected_strategy="TREND_PULLBACK_INTRADAY",
                paper_mode=self._mode_name,
                would_trade_if_exploration_enabled=False,
            )
        )

    def _persist_core_decision(
        self,
        *,
        timestamp: str,
        symbol: str,
        timeframe: str,
        decision: str,
        confidence: float,
        reasoning_summary: str,
        inputs: dict[str, Any],
    ) -> None:
        self._database.insert_agent_decision(
            AgentDecisionRecord(
                timestamp=timestamp,
                agent_name="IntradayCoreEngine",
                symbol=symbol,
                timeframe=timeframe,
                decision=decision,
                confidence=round(confidence, 6),
                inputs_used=json.dumps(inputs, ensure_ascii=True),
                reasoning_summary=reasoning_summary,
                linked_signal_id=None,
                linked_trade_id=None,
                provider_used="BINANCE",
                outcome_label="APPROVED" if decision in {"LONG", "SHORT"} else "REJECTED",
            )
        )

    def _persist_provider_probe_status(
        self,
        *,
        probes: Sequence[BinanceConnectivityProbe],
        provider_live_binance: bool,
    ) -> None:
        timestamp = datetime.now(timezone.utc).isoformat()
        error_messages = [probe.error_message for probe in probes if probe.error_message]
        self._database.insert_provider_status(
            ProviderStatusRecord(
                timestamp=timestamp,
                provider="BINANCE",
                status="OK" if provider_live_binance else "FAIL",
                latency_ms=float(sum(probe.latency_ms for probe in probes if probe.latency_ms >= 0) / max(len(probes), 1)),
                last_success_at=timestamp if provider_live_binance else None,
                last_error=" | ".join(message for message in error_messages if message) or None,
                last_error_at=timestamp if error_messages else None,
                source_type="LIVE",
                is_current_live_provider=provider_live_binance,
                raw_payload=json.dumps(
                    [
                        {
                            "name": probe.name,
                            "endpoint": probe.endpoint,
                            "ok": probe.ok,
                            "latency_ms": probe.latency_ms,
                            "interpretation": probe.interpretation,
                            "error_message": probe.error_message,
                            "response_preview": probe.response_preview,
                        }
                        for probe in probes
                    ],
                    ensure_ascii=True,
                ),
            )
        )

    def _persist_provider_error(self, *, symbol: str, timeframe: str, error: Exception) -> None:
        timestamp = datetime.now(timezone.utc).isoformat()
        self._database.insert_error_event(
            ErrorEventRecord(
                timestamp=timestamp,
                component="intraday_core_engine",
                symbol=f"{symbol}:{timeframe}",
                error_type=error.__class__.__name__,
                error_message=str(error),
                recoverable=True,
            )
        )
        self._database.insert_provider_status(
            ProviderStatusRecord(
                timestamp=timestamp,
                provider="BINANCE",
                status="FAIL",
                latency_ms=0.0,
                last_success_at=None,
                last_error=str(error),
                last_error_at=timestamp,
                source_type="LIVE",
                is_current_live_provider=False,
                raw_payload=json.dumps({"symbol": symbol, "timeframe": timeframe, "error": str(error)}, ensure_ascii=True),
            )
        )

    def _ensure_portfolio_initialized(self) -> None:
        if self._database.get_paper_portfolio() is not None:
            return
        now = datetime.now(timezone.utc).isoformat()
        record = PaperPortfolioRecord(
            timestamp=now,
            starting_capital=self._settings.simulated_initial_capital,
            available_cash=self._settings.simulated_initial_capital,
            realized_pnl=0.0,
            unrealized_pnl=0.0,
            total_equity=self._settings.simulated_initial_capital,
            drawdown=0.0,
            max_drawdown=0.0,
            gross_exposure=0.0,
            net_exposure=0.0,
            open_positions=0,
            total_fees_paid=0.0,
            total_slippage_paid=0.0,
        )
        self._database.upsert_paper_portfolio(record)
        self._database.append_paper_equity_curve(record)

    def _update_portfolio_snapshot(self, *, timestamp: str) -> None:
        portfolio = self._database.get_paper_portfolio() or {}
        starting_capital = float(portfolio.get("starting_capital", self._settings.simulated_initial_capital))
        open_trades = [trade for trade in self._database.get_open_simulated_trades() if trade.paper_mode == self._mode_name]
        closed_metrics = self._build_trade_metrics_for_mode()

        unrealized_pnl = 0.0
        gross_exposure = 0.0
        net_exposure = 0.0
        for trade in open_trades:
            latest_candle = self._database.get_recent_candles(trade.symbol, trade.timeframe, limit=1)
            if not latest_candle:
                continue
            mark = latest_candle[-1].close
            quantity = (trade.notional_exposure or 0.0) / trade.entry_price if trade.entry_price else 0.0
            unrealized = ((trade.entry_price - mark) * quantity) if trade.direction == "SHORT" else ((mark - trade.entry_price) * quantity)
            unrealized_pnl += unrealized
            gross_exposure += trade.notional_exposure or 0.0
            net_exposure += -(trade.notional_exposure or 0.0) if trade.direction == "SHORT" else (trade.notional_exposure or 0.0)

        realized_pnl = float(closed_metrics["total_pnl"])
        total_equity = starting_capital + realized_pnl + unrealized_pnl
        available_cash = starting_capital - sum((trade.margin_used or self._settings.intraday_core_position_size_usd) for trade in open_trades) + realized_pnl
        peak_equity = max(float(portfolio.get("total_equity", starting_capital)), total_equity, starting_capital)
        drawdown = total_equity - peak_equity
        max_drawdown = min(float(portfolio.get("max_drawdown", 0.0)), drawdown)

        record = PaperPortfolioRecord(
            timestamp=timestamp,
            starting_capital=round(starting_capital, 6),
            available_cash=round(available_cash, 6),
            realized_pnl=round(realized_pnl, 6),
            unrealized_pnl=round(unrealized_pnl, 6),
            total_equity=round(total_equity, 6),
            drawdown=round(drawdown, 6),
            max_drawdown=round(max_drawdown, 6),
            gross_exposure=round(gross_exposure, 6),
            net_exposure=round(net_exposure, 6),
            open_positions=len(open_trades),
            total_fees_paid=float(closed_metrics["total_fees_paid"]),
            total_slippage_paid=float(closed_metrics["total_slippage_paid"]),
        )
        self._database.upsert_paper_portfolio(record)
        self._database.append_paper_equity_curve(record)

    def _build_trade_metrics_for_mode(self) -> dict[str, float]:
        trades = [
            trade for trade in self._database.get_closed_simulated_trades()
            if trade.paper_mode == self._mode_name
        ]
        total_gross_pnl = sum(float(trade.gross_pnl or trade.pnl or 0.0) for trade in trades)
        total_net_pnl_before_funding = sum(float(trade.net_pnl_before_funding or trade.net_pnl or trade.pnl or 0.0) for trade in trades)
        total_pnl = sum(float(trade.final_net_pnl_after_all_costs or trade.net_pnl or trade.pnl or 0.0) for trade in trades)
        total_fees_paid = sum(float(trade.total_fees or trade.fees_paid or 0.0) for trade in trades)
        total_slippage_paid = sum(float(trade.slippage_cost or 0.0) for trade in trades)
        total_spread_paid = sum(float(trade.spread_cost or 0.0) for trade in trades)
        total_funding_cost = sum(float(trade.funding_cost_estimate or 0.0) for trade in trades)
        return {
            "total_gross_pnl": round(total_gross_pnl, 6),
            "total_net_pnl_before_funding": round(total_net_pnl_before_funding, 6),
            "total_pnl": round(total_pnl, 6),
            "total_fees_paid": round(total_fees_paid, 6),
            "total_slippage_paid": round(total_slippage_paid, 6),
            "total_spread_paid": round(total_spread_paid, 6),
            "total_funding_cost": round(total_funding_cost, 6),
        }

    @staticmethod
    def _map_net_gate_reasons(rejection_reasons: Sequence[str]) -> list[str]:
        simple_reasons: list[str] = []
        for reason in rejection_reasons:
            lowered = reason.lower()
            if "signal is not actionable" in lowered:
                simple_reasons.append("signal_not_actionable")
            elif "net reward/risk" in lowered:
                simple_reasons.append("net_reward_risk_too_low")
            elif any(marker in lowered for marker in ("expected net edge", "expected move", "cost drag", "minimum profitable move", "estimated costs", "covers ")):
                simple_reasons.append("costs_consume_target")
            elif "volatility headroom" in lowered:
                simple_reasons.append("signal_not_actionable")
        return simple_reasons or ["costs_consume_target"]

    @staticmethod
    def _binance_http_usable(probes: Sequence[BinanceConnectivityProbe]) -> bool:
        return all(probe.ok for probe in probes[:2]) if len(probes) >= 2 else all(probe.ok for probe in probes)

    @staticmethod
    def _sma(values: Sequence[float], length: int) -> float:
        if not values:
            return 0.0
        window = values[-length:] if len(values) >= length else values
        return sum(window) / len(window)

    @staticmethod
    def _atr_pct(candles: Sequence[Candle]) -> float:
        if len(candles) < 2:
            return 0.0
        true_ranges: list[float] = []
        previous_close = candles[0].close
        for candle in candles[1:]:
            true_range = max(candle.high - candle.low, abs(candle.high - previous_close), abs(candle.low - previous_close))
            base_price = previous_close if previous_close else candle.close
            true_ranges.append((true_range / base_price) * 100 if base_price else 0.0)
            previous_close = candle.close
        return sum(true_ranges) / len(true_ranges) if true_ranges else 0.0

    @staticmethod
    def _to_stored_candle(candle: Candle) -> StoredCandle:
        return StoredCandle(
            symbol=candle.symbol,
            timeframe=candle.timeframe,
            open_time=candle.open_time,
            open=candle.open,
            high=candle.high,
            low=candle.low,
            close=candle.close,
            volume=candle.volume,
            close_time=candle.close_time,
            provider=candle.provider,
        )
