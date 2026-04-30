from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import logging
import time
from typing import Sequence

from agents.audit_agent import AuditAgent
from agents.cost_model_agent import CostModelAgent
from agents.decision_orchestrator import AgentVote, DecisionOrchestrator
from agents.delta_agent import DeltaAgent
from agents.execution_simulator_agent import ExecutionSimulatorAgent
from agents.market_context_agent import MarketContextAgent
from agents.market_data_agent import MarketDataAgent
from agents.performance_learning_agent import PerformanceLearningAgent
from agents.risk_reward_agent import RiskRewardAgent
from agents.symbol_selection_agent import SymbolSelectionAgent
from analytics.performance_analyzer import PerformanceAnalyzer
from config.settings import Settings
from core.database import (
    AgentDecisionRecord,
    Database,
    ErrorEventRecord,
    MarketContextRecord,
    MarketSnapshotRecord,
    PaperPortfolioRecord,
    RejectedSignalRecord,
    SignalLogRecord,
)
from data.market_data_provider import ProviderRouter


logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class LivePaperEngineResult:
    loops_completed: int
    decisions_persisted: int
    trades_opened: int
    trades_closed: int


class LivePaperEngine:
    def __init__(
        self,
        *,
        database: Database,
        settings: Settings,
        provider_router: ProviderRouter,
        market_data_agent: MarketDataAgent,
        market_context_agent: MarketContextAgent,
        delta_agent: DeltaAgent,
        risk_reward_agent: RiskRewardAgent,
        cost_model_agent: CostModelAgent,
        performance_learning_agent: PerformanceLearningAgent,
        symbol_selection_agent: SymbolSelectionAgent,
        execution_simulator_agent: ExecutionSimulatorAgent,
        audit_agent: AuditAgent,
        decision_orchestrator: DecisionOrchestrator,
        performance_analyzer: PerformanceAnalyzer,
    ) -> None:
        self._database = database
        self._settings = settings
        self._provider_router = provider_router
        self._market_data_agent = market_data_agent
        self._market_context_agent = market_context_agent
        self._delta_agent = delta_agent
        self._risk_reward_agent = risk_reward_agent
        self._cost_model_agent = cost_model_agent
        self._performance_learning_agent = performance_learning_agent
        self._symbol_selection_agent = symbol_selection_agent
        self._execution_simulator_agent = execution_simulator_agent
        self._audit_agent = audit_agent
        self._decision_orchestrator = decision_orchestrator
        self._performance_analyzer = performance_analyzer

    def run(
        self,
        *,
        symbols: Sequence[str],
        timeframes: Sequence[str],
        max_loops: int | None,
        run_minutes: int | None,
        binance_http_ok: bool,
        allow_stale_fallback: bool,
    ) -> LivePaperEngineResult:
        deadline = datetime.now(timezone.utc) + timedelta(minutes=run_minutes) if run_minutes is not None else None
        loops_completed = 0
        decisions_persisted = 0
        trades_opened = 0
        trades_closed = 0

        self._ensure_portfolio_initialized()
        prefer_fallback = max_loops is not None and not binance_http_ok
        while True:
            loops_completed += 1
            loop_timestamp = datetime.now(timezone.utc).isoformat()
            logger.info(
                "Live paper engine cycle started",
                extra={
                    "event": "live_paper_cycle_start",
                    "context": {
                        "loop_count": loops_completed,
                        "symbols": list(symbols),
                        "timeframes": list(timeframes),
                    },
                },
            )

            for timeframe in timeframes:
                for symbol in symbols:
                    try:
                        persisted, opened, closed = self._process_symbol_timeframe(
                            symbol=symbol,
                            timeframe=timeframe,
                            timestamp=loop_timestamp,
                            prefer_fallback=prefer_fallback,
                            allow_stale_fallback=allow_stale_fallback,
                        )
                        decisions_persisted += persisted
                        trades_opened += opened
                        trades_closed += closed
                    except Exception as exc:
                        self._database.insert_error_event(
                            ErrorEventRecord(
                                timestamp=datetime.now(timezone.utc).isoformat(),
                                component="live_paper_engine",
                                symbol=f"{symbol}:{timeframe}",
                                error_type=exc.__class__.__name__,
                                error_message=str(exc),
                                recoverable=True,
                            )
                        )
                        logger.exception(
                            "Live paper symbol processing failed",
                            extra={
                                "event": "live_paper_symbol_error",
                                "context": {"symbol": symbol, "timeframe": timeframe, "error": str(exc)},
                            },
                        )

            self._update_portfolio_snapshot(timestamp=loop_timestamp)
            self._performance_analyzer.refresh()

            if max_loops is not None and loops_completed >= max_loops:
                break
            if deadline is not None and datetime.now(timezone.utc) >= deadline:
                break
            if max_loops is None:
                time.sleep(self._settings.continuous_loop_seconds)

        return LivePaperEngineResult(
            loops_completed=loops_completed,
            decisions_persisted=decisions_persisted,
            trades_opened=trades_opened,
            trades_closed=trades_closed,
        )

    def _process_symbol_timeframe(
        self,
        *,
        symbol: str,
        timeframe: str,
        timestamp: str,
        prefer_fallback: bool,
        allow_stale_fallback: bool,
    ) -> tuple[int, int, int]:
        provider_result = self._provider_router.fetch_latest_closed_candles(
            symbol=symbol,
            timeframe=timeframe,
            limit=20,
            prefer_fallback=prefer_fallback,
        )
        if provider_result.error_message:
            self._database.insert_error_event(
                ErrorEventRecord(
                    timestamp=timestamp,
                    component="market_data_provider",
                    symbol=f"{symbol}:{timeframe}",
                    error_type="PRIMARY_PROVIDER_FAILURE",
                    error_message=provider_result.error_message,
                    recoverable=True,
                )
            )

        if provider_result.candles:
            self._database.insert_candles(provider_result.candles)

        assessment = self._market_data_agent.assess(
            symbol=symbol,
            timeframe=timeframe,
            candles=provider_result.candles,
            provider_used=provider_result.provider_used,
        )
        notes: list[str] = list(assessment.notes)
        if provider_result.error_message:
            notes.append(f"fallback_reason={provider_result.error_message}")
        stale_fallback_allowed = (
            provider_result.provider_used == "LOCAL_SQLITE"
            and assessment.is_stale
            and allow_stale_fallback
        )
        if stale_fallback_allowed:
            notes.append("stale local fallback explicitly allowed by operator")
        notes_text = "; ".join(notes)
        latest_candle = provider_result.candles[-1] if provider_result.candles else None
        if latest_candle is None:
            self._persist_agent_decision(
                timestamp=timestamp,
                agent_name="MarketDataAgent",
                symbol=symbol,
                timeframe=timeframe,
                decision="REJECT",
                confidence=assessment.confidence,
                inputs={"provider_used": provider_result.provider_used},
                reasoning_summary=notes_text or "No candles available",
                provider_used=provider_result.provider_used,
            )
            return 1, 0, 0

        self._database.insert_market_snapshot(
            MarketSnapshotRecord(
                timestamp=latest_candle.close_time,
                symbol=symbol,
                timeframe=timeframe,
                provider_used=provider_result.provider_used,
                open_price=latest_candle.open,
                high_price=latest_candle.high,
                low_price=latest_candle.low,
                close_price=latest_candle.close,
                volume=latest_candle.volume,
                is_valid=assessment.is_valid,
                is_stale=assessment.is_stale,
                notes=notes_text,
            )
        )
        market_data_decision = "OK_FALLBACK" if stale_fallback_allowed else assessment.vote
        market_data_confidence = 0.35 if stale_fallback_allowed else assessment.confidence
        self._persist_agent_decision(
            timestamp=latest_candle.close_time,
            agent_name="MarketDataAgent",
            symbol=symbol,
            timeframe=timeframe,
            decision=market_data_decision,
            confidence=market_data_confidence,
            inputs={**assessment.as_dict(), "fallback_reason": provider_result.error_message, "stale_fallback_allowed": stale_fallback_allowed},
            reasoning_summary=notes_text or "Market data agent completed validation",
            provider_used=provider_result.provider_used,
        )

        recent_candles = self._database.get_recent_candles(symbol=symbol, timeframe=timeframe, limit=20)
        market_context = self._market_context_agent.evaluate(symbol=symbol, timeframe=timeframe, candles=recent_candles)
        timeframe_contexts = self._build_timeframe_contexts(
            symbol=symbol,
            execution_timeframe=timeframe,
            current_context=market_context,
        )
        self._database.insert_market_context(
            MarketContextRecord(
                timestamp=latest_candle.close_time,
                source="MarketContextAgent",
                macro_regime=str(market_context["macro_regime"]),
                risk_regime=str(market_context["risk_regime"]),
                context_score=float(market_context["context_score"]),
                reason=str(market_context["reason"]),
                raw_payload=json.dumps(market_context, ensure_ascii=True),
                provider_used=provider_result.provider_used,
            )
        )
        self._persist_agent_decision(
            timestamp=latest_candle.close_time,
            agent_name="MarketContextAgent",
            symbol=symbol,
            timeframe=timeframe,
            decision=str(market_context["market_regime"]),
            confidence=float(market_context["context_score"]),
            inputs=market_context,
            reasoning_summary=str(market_context["reason"]),
            provider_used=provider_result.provider_used,
        )

        signal = self._delta_agent.evaluate_from_candles(
            symbol=symbol,
            timeframe=timeframe,
            candles=recent_candles,
            market_context=market_context,
            relaxation_factor=1.0,
        )
        signal["provider_used"] = provider_result.provider_used
        signal["data_stale"] = assessment.is_stale
        signal["fallback_reason"] = provider_result.error_message
        signal["stale_fallback_allowed"] = stale_fallback_allowed
        signal["signal_type"] = "NO_TRADE" if str(signal["signal_type"]) == "NONE" else signal["signal_type"]
        self._database.insert_signal_log(
            SignalLogRecord(
                symbol=symbol,
                timeframe=timeframe,
                signal=str(signal["signal_type"]),
                signal_tier=str(signal["signal_tier"]),
                k_value=float(signal["k_value"]),
                confidence=float(signal["confidence"]),
                timestamp=str(signal["timestamp"]),
                provider_used=provider_result.provider_used,
            )
        )
        self._persist_agent_decision(
            timestamp=str(signal["timestamp"]),
            agent_name="DeltaAgent",
            symbol=symbol,
            timeframe=timeframe,
            decision=str(signal["signal_type"]),
            confidence=float(signal["confidence"]),
            inputs=signal,
            reasoning_summary=str(signal["explanation"]),
            provider_used=provider_result.provider_used,
        )

        projected_direction = str(signal["signal_type"]) if str(signal["signal_type"]) in {"LONG", "SHORT"} else str(signal.get("direction", "LONG"))
        cost_snapshot = self._cost_model_agent.estimate(
            entry_price=latest_candle.close,
            direction=projected_direction,
            position_size_usd=self._settings.simulated_position_size_usd,
            volatility_pct=float(signal.get("volatility_pct", 0.0)),
        )
        risk_reward = self._risk_reward_agent.evaluate(
            signal=signal,
            cost_snapshot=cost_snapshot,
        )
        self._persist_agent_decision(
            timestamp=str(signal["timestamp"]),
            agent_name="RiskRewardAgent",
            symbol=symbol,
            timeframe=timeframe,
            decision=risk_reward.vote,
            confidence=risk_reward.confidence,
            inputs=risk_reward.as_dict(),
            reasoning_summary=risk_reward.reason,
            provider_used=provider_result.provider_used,
        )

        symbol_selection = self._symbol_selection_agent.evaluate(
            symbol=symbol,
            timeframe=timeframe,
            candles=recent_candles,
            market_context=market_context,
            gap_count=assessment.gap_count,
            duplicate_count=assessment.duplicate_count,
            corrupted_count=assessment.corrupted_count,
            estimated_cost_drag_pct=float(cost_snapshot.cost_drag_pct),
        )
        self._persist_agent_decision(
            timestamp=str(signal["timestamp"]),
            agent_name="SymbolSelectionAgent",
            symbol=symbol,
            timeframe=timeframe,
            decision="TRADABLE" if symbol_selection.tradable_today else "REJECT",
            confidence=float(symbol_selection.symbol_score),
            inputs=symbol_selection.as_dict(),
            reasoning_summary=symbol_selection.reason,
            provider_used=provider_result.provider_used,
        )

        learning = self._performance_learning_agent.assess(
            setup_signature=str(signal.get("setup_signature", "UNKNOWN")),
            direction="LONG" if str(signal["signal_type"]) == "NO_TRADE" else str(signal["signal_type"]),
        )
        adjusted_confidence = max(0.0, min(1.0, float(signal["confidence"]) + learning.confidence_adjustment))
        signal["confidence"] = round(adjusted_confidence, 6)
        self._persist_agent_decision(
            timestamp=str(signal["timestamp"]),
            agent_name="PerformanceLearningAgent",
            symbol=symbol,
            timeframe=timeframe,
            decision=learning.vote,
            confidence=abs(learning.confidence_adjustment),
            inputs=learning.as_dict(),
            reasoning_summary=learning.reason,
            provider_used=provider_result.provider_used,
        )

        votes = [
            AgentVote("MarketDataAgent", "OK" if stale_fallback_allowed else assessment.vote, market_data_confidence, notes_text or "validation complete"),
            AgentVote("DeltaAgent", str(signal["signal_type"]), float(signal["confidence"]), str(signal["reason"]), tuple(signal.get("risks_detected", ()))),
            AgentVote("RiskRewardAgent", risk_reward.vote, risk_reward.confidence, risk_reward.reason),
            AgentVote("SymbolSelectionAgent", "OK" if symbol_selection.tradable_today else "REJECT", float(symbol_selection.symbol_score), symbol_selection.reason),
            AgentVote("PerformanceLearningAgent", learning.vote, abs(learning.confidence_adjustment), learning.reason),
        ]
        proposed_direction = "NO_TRADE" if str(signal["signal_type"]) == "NO_TRADE" else str(signal["signal_type"])
        timeframe_alignment = self._decision_orchestrator.assess_timeframes(
            symbol=symbol,
            direction=proposed_direction if proposed_direction in {"LONG", "SHORT"} else str(signal.get("direction", "LONG")),
            execution_timeframe=timeframe,
            timeframe_contexts=timeframe_contexts,
        )
        orchestrated = self._decision_orchestrator.decide(
            signal_tier=str(signal["signal_tier"]),
            proposed_direction=proposed_direction,
            votes=votes,
            current_open_positions=len(self._database.get_open_paper_positions()),
            timeframe_alignment=timeframe_alignment,
            symbol_selection_ok=symbol_selection.tradable_today,
        )
        self._persist_agent_decision(
            timestamp=str(signal["timestamp"]),
            agent_name="DecisionOrchestrator",
            symbol=symbol,
            timeframe=timeframe,
            decision=orchestrated.final_decision,
            confidence=orchestrated.final_confidence,
            inputs={"votes": [vote.as_dict() for vote in votes], "timeframe_alignment": timeframe_alignment.as_dict()},
            reasoning_summary=orchestrated.explanation,
            provider_used=provider_result.provider_used,
        )

        audit = self._audit_agent.explain_entry(
            final_decision=orchestrated.final_decision,
            approved=orchestrated.approved,
            signal_reason=str(signal["reason"]),
            risk_reason=risk_reward.reason,
            learning_reason=learning.reason,
            cost_snapshot=cost_snapshot.as_dict(),
            committee_notes=orchestrated.committee_notes,
        )

        signal["agent_votes"] = [vote.as_dict() for vote in votes]
        signal["risk_reward_snapshot"] = risk_reward.as_dict()
        signal["cost_snapshot"] = cost_snapshot.as_dict()
        signal["timeframe_alignment"] = timeframe_alignment.timeframe_alignment
        signal["dominant_trend_timeframe"] = timeframe_alignment.dominant_trend_timeframe
        signal["execution_timeframe"] = timeframe_alignment.execution_timeframe
        signal["context_timeframe_votes"] = timeframe_alignment.context_timeframe_votes
        signal["structural_bias"] = timeframe_alignment.structural_bias
        signal["alignment_score"] = timeframe_alignment.alignment_score
        signal["contradiction_score"] = timeframe_alignment.contradiction_score
        signal["final_timeframe_reason"] = timeframe_alignment.final_timeframe_reason
        signal["symbol_score"] = symbol_selection.symbol_score
        signal["liquidity_score"] = symbol_selection.liquidity_score
        signal["volatility_score"] = symbol_selection.volatility_score
        signal["spread_score"] = symbol_selection.spread_score
        signal["data_quality_score"] = symbol_selection.data_quality_score
        signal["institutional_proxy_score"] = symbol_selection.institutional_proxy_score
        signal["tradable_today"] = symbol_selection.tradable_today
        signal["explanation"] = audit.summary
        signal["decision_type"] = orchestrated.decision_type
        signal["signal_type"] = "NONE" if not orchestrated.approved else orchestrated.final_decision
        signal["leverage_simulated"] = self._settings.simulated_default_leverage

        self._handle_live_exit_overrides(symbol=symbol, timeframe=timeframe, latest_candle=latest_candle, market_context=market_context)
        execution_result = self._execution_simulator_agent.process_cycle(
            symbol=symbol,
            timeframe=timeframe,
            signal=signal,
            latest_candle=recent_candles[-1],
            signal_id=None,
            current_time=latest_candle.close_time,
            provider_used=provider_result.provider_used,
        )

        if not orchestrated.approved:
            self._database.insert_rejected_signal(
                RejectedSignalRecord(
                    symbol=symbol,
                    timeframe=timeframe,
                    signal_tier=str(signal["signal_tier"]),
                    reason=orchestrated.explanation,
                    context_payload=json.dumps(
                        {
                            "provider_used": provider_result.provider_used,
                            "signal": signal,
                            "risk_reward": risk_reward.as_dict(),
                            "learning": learning.as_dict(),
                            "committee": orchestrated.as_dict(),
                        },
                        ensure_ascii=True,
                    ),
                    thresholds_failed=json.dumps(list(signal.get("thresholds_failed", ())), ensure_ascii=True),
                    timestamp=str(signal["timestamp"]),
                )
            )

        self._label_recent_no_trade_decisions(symbol=symbol, timeframe=timeframe)
        logger.info(
            "Live paper decision processed",
            extra={
                "event": "live_paper_decision",
                "context": {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "provider_used": provider_result.provider_used,
                    "delta_signal": signal["decision_type"],
                    "final_decision": orchestrated.final_decision,
                    "approved": orchestrated.approved,
                    "confidence": orchestrated.final_confidence,
                    "trade_opened": execution_result.cycle_result.opened,
                    "trade_closed": execution_result.cycle_result.closed,
                },
            },
        )
        return 7, int(execution_result.cycle_result.opened), int(execution_result.cycle_result.closed)

    def _build_timeframe_contexts(
        self,
        *,
        symbol: str,
        execution_timeframe: str,
        current_context: dict[str, object],
    ) -> dict[str, dict[str, object]]:
        contexts: dict[str, dict[str, object]] = {execution_timeframe: current_context}
        for timeframe in (*self._settings.context_timeframes, *self._settings.structural_timeframes):
            if timeframe == execution_timeframe:
                continue
            candles = self._database.get_recent_candles(symbol=symbol, timeframe=timeframe, limit=20)
            if len(candles) < 5:
                continue
            contexts[timeframe] = self._market_context_agent.evaluate(
                symbol=symbol,
                timeframe=timeframe,
                candles=candles,
            )
        return contexts

    def _persist_agent_decision(
        self,
        *,
        timestamp: str,
        agent_name: str,
        symbol: str,
        timeframe: str,
        decision: str,
        confidence: float,
        inputs: dict[str, object],
        reasoning_summary: str,
        provider_used: str,
    ) -> int:
        return self._database.insert_agent_decision(
            AgentDecisionRecord(
                timestamp=timestamp,
                agent_name=agent_name,
                symbol=symbol,
                timeframe=timeframe,
                decision=decision,
                confidence=confidence,
                inputs_used=json.dumps(inputs, ensure_ascii=True),
                reasoning_summary=reasoning_summary,
                linked_signal_id=None,
                linked_trade_id=None,
                provider_used=provider_used,
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
        open_trades = self._database.get_open_simulated_trades()
        closed_metrics = self._database.get_simulated_trade_metrics()

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
        available_cash = starting_capital - sum((trade.margin_used or self._settings.simulated_position_size_usd) for trade in open_trades) + realized_pnl
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

    def _handle_live_exit_overrides(
        self,
        *,
        symbol: str,
        timeframe: str,
        latest_candle,
        market_context: dict[str, object],
    ) -> None:
        trade = self._database.get_open_simulated_trade(symbol, timeframe)
        if trade is None:
            return
        regime = str(market_context.get("market_regime", "RANGING"))
        trend = str(market_context.get("trend_direction", "SIDEWAYS"))
        if trade.entry_market_regime == "TRENDING" and regime == "RANGING":
            self._execution_simulator_agent._tracker.force_close_trade(
                symbol=symbol,
                timeframe=timeframe,
                latest_candle=latest_candle,
                reason_exit="Exited early because market regime deteriorated from trending to ranging",
                status="CLOSED",
                exit_context={"close_reason": "regime_change"},
            )
            return
        if trade.direction == "LONG" and trend == "DOWN":
            self._execution_simulator_agent._tracker.force_close_trade(
                symbol=symbol,
                timeframe=timeframe,
                latest_candle=latest_candle,
                reason_exit="Exited early because live trend turned against the long position",
                status="CLOSED",
                exit_context={"close_reason": "trend_reversal"},
            )
        elif trade.direction == "SHORT" and trend == "UP":
            self._execution_simulator_agent._tracker.force_close_trade(
                symbol=symbol,
                timeframe=timeframe,
                latest_candle=latest_candle,
                reason_exit="Exited early because live trend turned against the short position",
                status="CLOSED",
                exit_context={"close_reason": "trend_reversal"},
            )

    def _label_recent_no_trade_decisions(self, *, symbol: str, timeframe: str) -> None:
        pending = self._database.get_pending_no_trade_decisions(timeframe=timeframe, limit=20)
        for row in pending:
            if row["symbol"] != symbol:
                continue
            future_candles = self._database.get_candles_after_close_time(
                symbol=symbol,
                timeframe=timeframe,
                close_time=row["timestamp"],
                limit=self._settings.simulated_max_hold_candles,
            )
            if len(future_candles) < self._settings.simulated_max_hold_candles:
                continue
            try:
                payload = json.loads(row["inputs_used"])
            except json.JSONDecodeError:
                payload = {}
            reference_price = float(payload.get("price", future_candles[0].close))
            max_move = max(abs(((candle.close - reference_price) / reference_price) * 100) for candle in future_candles) if reference_price else 0.0
            if max_move >= self._settings.simulated_take_profit_pct * 100:
                outcome_label = "MISSED_OPPORTUNITY"
            else:
                outcome_label = "GOOD_AVOIDANCE"
            self._database.update_agent_decision_outcome(decision_id=int(row["id"]), outcome_label=outcome_label)
