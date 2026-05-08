from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import json
from typing import Any

from agents.breakout_agent import BreakoutAgent
from agents.cost_model_agent import CostModelAgent
from agents.decision_orchestrator import DecisionOrchestrator, TimeframeAlignment
from agents.delta_agent import DeltaAgent
from agents.market_context_agent import MarketContextAgent
from agents.market_data_agent import MarketDataAgent
from agents.market_state_agent import MarketStateAgent
from agents.mean_reversion_agent import MeanReversionAgent
from agents.meta_learning_agent import MetaLearningAgent
from agents.momentum_scalp_agent import MomentumScalpAgent
from agents.net_profitability_gate import NetProfitabilityGate
from agents.pullback_continuation_agent import PullbackContinuationAgent
from agents.risk_manager_agent import RiskManagerAgent
from agents.risk_reward_agent import RiskRewardAgent
from agents.strategy_critic_agent import StrategyCriticAgent
from agents.strategy_selection_agent import StrategySelectionAgent
from agents.symbol_selection_agent import SymbolSelectionAgent
from agents.trend_following_agent import StrategyProposal, TrendFollowingAgent
from config.settings import Settings
from core.database import (
    AgentDecisionRecord,
    BrainDecisionRecord,
    DataQualityEventRecord,
    Database,
    GapRepairEventRecord,
    MarketContextRecord,
    MarketSnapshotRecord,
    ProviderStatusRecord,
    RejectedSignalRecord,
    RiskEventRecord,
    StrategyVoteRecord,
)
from core.ledger_reconciler import LedgerReconciler
from data.market_data_provider import ProviderRouter
from data.live_context_fusion import build_symbol_context_bias
from features.feature_store import FeatureStore


@dataclass(slots=True, frozen=True)
class BrainDecision:
    symbol: str
    timeframe: str
    final_decision: str
    selected_strategy: str
    market_state: str
    risk_mode: str
    confidence: float
    final_score: float
    expected_move_pct: float
    total_cost_pct: float
    expected_net_edge_pct: float
    risk_reward_ratio: float
    cost_coverage_multiple: float
    approved: bool
    rejection_reason: str
    entry_reason: str
    exit_reason: str
    provider_used: str
    data_stale: bool
    paper_mode: str
    raw_payload: dict[str, object]

    def as_dict(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "final_decision": self.final_decision,
            "selected_strategy": self.selected_strategy,
            "market_state": self.market_state,
            "risk_mode": self.risk_mode,
            "confidence": self.confidence,
            "final_score": self.final_score,
            "expected_move_pct": self.expected_move_pct,
            "total_cost_pct": self.total_cost_pct,
            "expected_net_edge_pct": self.expected_net_edge_pct,
            "risk_reward_ratio": self.risk_reward_ratio,
            "cost_coverage_multiple": self.cost_coverage_multiple,
            "approved": self.approved,
            "rejection_reason": self.rejection_reason,
            "entry_reason": self.entry_reason,
            "exit_reason": self.exit_reason,
            "provider_used": self.provider_used,
            "data_stale": self.data_stale,
            "paper_mode": self.paper_mode,
            "raw_payload": self.raw_payload,
        }


class TradingBrainOrchestrator:
    def __init__(
        self,
        *,
        database: Database,
        settings: Settings,
        provider_router: ProviderRouter,
        market_data_agent: MarketDataAgent,
        market_context_agent: MarketContextAgent,
        delta_agent: DeltaAgent,
        symbol_selection_agent: SymbolSelectionAgent,
        cost_model_agent: CostModelAgent,
        risk_reward_agent: RiskRewardAgent,
        net_profitability_gate: NetProfitabilityGate,
        decision_orchestrator: DecisionOrchestrator,
        feature_store: FeatureStore,
        market_state_agent: MarketStateAgent,
        strategy_selection_agent: StrategySelectionAgent,
        strategy_critic_agent: StrategyCriticAgent,
        risk_manager_agent: RiskManagerAgent,
        meta_learning_agent: MetaLearningAgent,
        ledger_reconciler: LedgerReconciler,
    ) -> None:
        self._database = database
        self._settings = settings
        self._provider_router = provider_router
        self._market_data_agent = market_data_agent
        self._market_context_agent = market_context_agent
        self._delta_agent = delta_agent
        self._symbol_selection_agent = symbol_selection_agent
        self._cost_model_agent = cost_model_agent
        self._risk_reward_agent = risk_reward_agent
        self._net_profitability_gate = net_profitability_gate
        self._decision_orchestrator = decision_orchestrator
        self._feature_store = feature_store
        self._market_state_agent = market_state_agent
        self._strategy_selection_agent = strategy_selection_agent
        self._strategy_critic_agent = strategy_critic_agent
        self._risk_manager_agent = risk_manager_agent
        self._meta_learning_agent = meta_learning_agent
        self._ledger_reconciler = ledger_reconciler
        self._strategy_agents = {
            "TREND_FOLLOWING": TrendFollowingAgent(),
            "BREAKOUT": BreakoutAgent(),
            "MEAN_REVERSION": MeanReversionAgent(),
            "MOMENTUM_SCALP": MomentumScalpAgent(),
            "PULLBACK_CONTINUATION": PullbackContinuationAgent(),
        }

    def decide_for_symbol(
        self,
        *,
        symbol: str,
        timeframe: str,
        prefer_fallback: bool,
        allow_stale_fallback: bool,
        observer_mode: bool,
        operating_horizon_minutes: int | None = None,
    ) -> BrainDecision:
        timestamp = datetime.now(timezone.utc).isoformat()
        provider_result = self._provider_router.fetch_latest_closed_candles(
            symbol=symbol,
            timeframe=timeframe,
            limit=max(self._settings.feature_store_lookback, 20),
            prefer_fallback=prefer_fallback,
        )
        for candle in provider_result.candles:
            self._database.insert_candles([candle])
        self._database.insert_provider_status(
            ProviderStatusRecord(
                timestamp=timestamp,
                provider=provider_result.provider_used,
                status="OK" if provider_result.candles else "FAIL",
                latency_ms=0.0,
                last_success_at=timestamp if provider_result.candles else None,
                last_error=provider_result.error_message,
                last_error_at=timestamp if provider_result.error_message else None,
                source_type="FALLBACK" if provider_result.used_fallback else "LIVE",
                is_current_live_provider=bool(provider_result.candles and not provider_result.used_fallback),
                raw_payload=json.dumps(
                    {
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "used_fallback": provider_result.used_fallback,
                        "error_message": provider_result.error_message,
                    },
                    ensure_ascii=True,
                ),
            )
        )
        assessment = self._market_data_agent.assess(
            symbol=symbol,
            timeframe=timeframe,
            candles=provider_result.candles,
            provider_used=provider_result.provider_used,
        )
        self._database.insert_data_quality_event(
            DataQualityEventRecord(
                timestamp=timestamp,
                symbol=symbol,
                timeframe=timeframe,
                event_type="MARKET_DATA_ASSESSMENT",
                severity="INFO" if assessment.is_valid else "WARNING",
                reason="; ".join(assessment.notes) or "assessment completed",
                raw_payload=json.dumps(assessment.as_dict(), ensure_ascii=True),
            )
        )
        if not provider_result.candles:
            return self._reject(symbol, timeframe, "NO_TRADE", "UNKNOWN", "DO_NOT_TRADE", provider_result.provider_used, True, "no candles available", {})

        recent_candles = self._database.get_recent_candles(symbol=symbol, timeframe=timeframe, limit=max(self._settings.feature_store_lookback, 20))
        latest_candle = recent_candles[-1]
        self._database.insert_market_snapshot(
            MarketSnapshotRecord(
                timestamp=timestamp,
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
                notes="; ".join(assessment.notes) or "brain snapshot recorded",
            )
        )
        if assessment.gap_count:
            self._database.insert_gap_repair_event(
                GapRepairEventRecord(
                    timestamp=timestamp,
                    symbol=symbol,
                    timeframe=timeframe,
                    gaps_detected=assessment.gap_count,
                    gaps_repaired=0,
                    provider_used=provider_result.provider_used,
                    reason="gaps detected during brain market validation",
                    raw_payload=json.dumps(assessment.as_dict(), ensure_ascii=True),
                )
            )
        market_context = self._market_context_agent.evaluate(symbol=symbol, timeframe=timeframe, candles=recent_candles)
        self._database.insert_market_context(
            MarketContextRecord(
                timestamp=timestamp,
                source="MarketContextAgent",
                macro_regime=str(market_context.get("macro_regime", "UNKNOWN")),
                risk_regime=str(market_context.get("risk_regime", "UNKNOWN")),
                context_score=float(market_context.get("context_score", 0.0)),
                reason=str(market_context.get("reason", "brain context evaluation")),
                raw_payload=json.dumps(market_context, ensure_ascii=True),
                provider_used=provider_result.provider_used,
            )
        )
        symbol_selection = self._symbol_selection_agent.evaluate(
            symbol=symbol,
            timeframe=timeframe,
            candles=recent_candles,
            market_context=market_context,
            gap_count=assessment.gap_count,
            duplicate_count=assessment.duplicate_count,
            corrupted_count=assessment.corrupted_count,
            estimated_cost_drag_pct=self._settings.max_cost_drag_pct,
        )
        feature_snapshot = self._feature_store.build(
            symbol=symbol,
            timeframe=timeframe,
            candles=recent_candles,
            quality_score=symbol_selection.data_quality_score,
            provider=provider_result.provider_used,
        )
        portfolio = self._database.get_paper_portfolio() or {}
        starting_capital = float(portfolio.get("starting_capital", self._settings.simulated_initial_capital))
        total_equity = float(portfolio.get("total_equity", starting_capital))
        drawdown_pct = ((total_equity - starting_capital) / starting_capital) * 100 if starting_capital else 0.0
        market_state = self._market_state_agent.assess(
            features=feature_snapshot.payload,
            market_context=market_context,
            is_stale=assessment.is_stale and not allow_stale_fallback,
            data_quality_score=symbol_selection.data_quality_score,
            recent_drawdown_pct=drawdown_pct,
        )
        selection = self._strategy_selection_agent.select(
            market_state=market_state.market_state,
            risk_mode=market_state.recommended_risk_mode,
            expected_cost_drag=float(feature_snapshot.payload.get("estimated_cost_drag", 0.0)),
        )
        risk_manager = self._risk_manager_agent.assess(
            ledger_report=self._ledger_reconciler.inspect(),
            market_risk_mode=market_state.recommended_risk_mode,
            current_drawdown_pct=drawdown_pct,
            loss_streak=self._loss_streak(),
            open_positions=len(self._database.get_open_paper_positions()),
            stale_data=assessment.is_stale and not allow_stale_fallback,
        )
        if risk_manager.recommended_action == "BLOCK":
            self._database.insert_risk_event(
                RiskEventRecord(
                    timestamp=timestamp,
                    event_type="RISK_BLOCK",
                    severity="WARNING",
                    symbol=symbol,
                    reason=risk_manager.reason,
                    action_taken="NO_TRADE",
                    raw_payload=json.dumps(risk_manager.as_dict(), ensure_ascii=True),
                )
            )

        timeframe_contexts = self._build_timeframe_contexts(
            symbol=symbol,
            execution_timeframe=timeframe,
            current_context=market_context,
            operating_horizon_minutes=operating_horizon_minutes,
            prefer_fallback=prefer_fallback,
        )
        direction_bias = "LONG" if market_state.trend_state == "UP" else "SHORT" if market_state.trend_state == "DOWN" else "NONE"
        proposals = self._collect_strategy_proposals(
            symbol=symbol,
            timeframe=timeframe,
            features=feature_snapshot.payload,
            market_state=market_state.as_dict(),
            direction_bias=direction_bias,
            selection=selection,
        )
        best_proposal = max(proposals, key=lambda item: item.confidence)

        proposal_stop_loss_price = None
        proposal_take_profit_price = None
        if best_proposal.proposed_decision in {"LONG", "SHORT"}:
            proposal_stop_loss_price, proposal_take_profit_price = self._proposal_price_levels(
                entry_price=recent_candles[-1].close,
                direction=best_proposal.proposed_decision,
                proposal=best_proposal,
            )

        exploration_position_size = max(
            min(
                self._settings.exploration_position_size_usd,
                total_equity * self._settings.exploration_risk_per_trade_pct,
                self._settings.simulated_position_size_usd * 0.6,
                total_equity * max(risk_manager.position_size_pct, 0.03),
            ),
            1.0,
        )
        cost_snapshot = self._cost_model_agent.estimate(
            entry_price=recent_candles[-1].close,
            direction=best_proposal.proposed_decision if best_proposal.proposed_decision in {"LONG", "SHORT"} else "LONG",
            position_size_usd=min(self._settings.simulated_position_size_usd, total_equity * risk_manager.position_size_pct),
            volatility_pct=float(feature_snapshot.payload.get("atr_pct", 0.0)),
            market_type=self._settings.simulated_market_type,
            stop_loss_price=proposal_stop_loss_price,
            take_profit_price=proposal_take_profit_price,
        )
        delta_context = dict(market_context)
        delta_signal = self._delta_agent.evaluate_from_candles(
            symbol=symbol,
            timeframe=timeframe,
            candles=recent_candles[-2:],
            market_context=delta_context,
            relaxation_factor=1.0,
        )
        if best_proposal.proposed_decision in {"LONG", "SHORT"}:
            delta_signal["signal_type"] = best_proposal.proposed_decision
            delta_signal["direction"] = best_proposal.proposed_decision
            delta_signal["decision_type"] = best_proposal.proposed_decision
            delta_signal["confidence"] = max(float(delta_signal.get("confidence", 0.0)), best_proposal.confidence)
        delta_signal["position_size_usd"] = min(self._settings.simulated_position_size_usd, total_equity * risk_manager.position_size_pct)
        risk_reward = self._risk_reward_agent.evaluate(signal=delta_signal, cost_snapshot=cost_snapshot)
        tf_alignment = self._decision_orchestrator.assess_timeframes(
            symbol=symbol,
            direction=best_proposal.proposed_decision if best_proposal.proposed_decision in {"LONG", "SHORT"} else direction_bias,
            execution_timeframe=timeframe,
            timeframe_contexts=timeframe_contexts,
            operating_horizon_minutes=operating_horizon_minutes,
        )
        risk_manager = self._relax_intraday_risk_manager(
            risk_manager=risk_manager,
            market_state=market_state.as_dict(),
            best_proposal=best_proposal,
            timeframe=timeframe,
            provider_used=provider_result.provider_used,
            assessment_is_stale=assessment.is_stale and not allow_stale_fallback,
            symbol_tradable=symbol_selection.tradable_today,
            data_quality_score=symbol_selection.data_quality_score,
            alignment=tf_alignment,
            operating_horizon_minutes=operating_horizon_minutes,
        )
        duplicate_setup = False
        if best_proposal.proposed_decision in {"LONG", "SHORT"}:
            duplicate_setup = self._is_duplicate_setup(symbol=symbol, timeframe=timeframe, direction=best_proposal.proposed_decision, setup_signature=best_proposal.strategy_name)
        symbol_has_open_trade = self._has_open_trade_for_symbol(symbol=symbol)
        external_context_bias = self._build_external_context_bias(
            symbol=symbol,
            direction=best_proposal.proposed_decision if best_proposal.proposed_decision in {"LONG", "SHORT"} else "NONE",
        )
        if external_context_bias["risk_event"]:
            self._database.insert_risk_event(
                RiskEventRecord(
                    timestamp=timestamp,
                    event_type="EXTERNAL_CONTEXT_RISK",
                    severity="WARNING" if external_context_bias["news_conflict"] else "INFO",
                    symbol=symbol,
                    reason=external_context_bias["reason"],
                    action_taken="CONTEXT_ONLY",
                    raw_payload=json.dumps(external_context_bias, ensure_ascii=True),
                )
            )
        best_proposal = self._apply_external_context_to_proposal(
            proposal=best_proposal,
            external_context_bias=external_context_bias,
        )
        risk_manager = self._apply_external_context_to_risk_manager(
            risk_manager=risk_manager,
            external_context_bias=external_context_bias,
        )
        tf_alignment = self._apply_external_context_to_alignment(
            alignment=tf_alignment,
            external_context_bias=external_context_bias,
        )
        selective_position_size = max(
            1.0,
            min(
                self._settings.simulated_position_size_usd,
                total_equity * max(risk_manager.position_size_pct, 0.0),
            ),
        )
        proposal_stop_loss_price = None
        proposal_take_profit_price = None
        if best_proposal.proposed_decision in {"LONG", "SHORT"}:
            proposal_stop_loss_price, proposal_take_profit_price = self._proposal_price_levels(
                entry_price=recent_candles[-1].close,
                direction=best_proposal.proposed_decision,
                proposal=best_proposal,
            )
        cost_snapshot = self._cost_model_agent.estimate(
            entry_price=recent_candles[-1].close,
            direction=best_proposal.proposed_decision if best_proposal.proposed_decision in {"LONG", "SHORT"} else "LONG",
            position_size_usd=selective_position_size,
            volatility_pct=float(feature_snapshot.payload.get("atr_pct", 0.0)),
            market_type=self._settings.simulated_market_type,
            stop_loss_price=proposal_stop_loss_price,
            take_profit_price=proposal_take_profit_price,
        )
        exploration_cost_snapshot = self._cost_model_agent.estimate(
            entry_price=recent_candles[-1].close,
            direction=best_proposal.proposed_decision if best_proposal.proposed_decision in {"LONG", "SHORT"} else "LONG",
            position_size_usd=exploration_position_size,
            volatility_pct=float(feature_snapshot.payload.get("atr_pct", 0.0)),
            market_type=self._settings.simulated_market_type,
            stop_loss_price=proposal_stop_loss_price,
            take_profit_price=proposal_take_profit_price,
        )
        exploration_signal = dict(delta_signal)
        exploration_signal["position_size_usd"] = exploration_position_size
        similar_trade_stats = self._database.get_similar_closed_trade_stats(
            setup_signature=best_proposal.strategy_name,
            direction=best_proposal.proposed_decision if best_proposal.proposed_decision in {"LONG", "SHORT"} else "LONG",
        )
        fallback_probability = (
            self._settings.paper_exploration_base_win_probability
            if similar_trade_stats["total"] < self._settings.min_sample_size_for_profitability_claim
            else max(0.05, min(0.95, float(similar_trade_stats["wins"]) / max(int(similar_trade_stats["total"]), 1)))
        )
        exploration_signal["probability_win"] = fallback_probability
        delta_signal["probability_win"] = (
            self._settings.paper_selective_base_win_probability
            if similar_trade_stats["total"] < self._settings.min_sample_size_for_profitability_claim
            else max(0.05, min(0.95, float(similar_trade_stats["wins"]) / max(int(similar_trade_stats["total"]), 1)))
        )
        exploration_gate = self._net_profitability_gate.evaluate(
            signal=exploration_signal,
            cost_snapshot=exploration_cost_snapshot,
            risk_mode=risk_manager.risk_mode,
            paper_mode="PAPER_EXPLORATION",
        )
        selective_gate = self._net_profitability_gate.evaluate(
            signal=delta_signal,
            cost_snapshot=cost_snapshot,
            risk_mode=risk_manager.risk_mode,
            paper_mode="PAPER_SELECTIVE",
        )
        signal_actionability = self._classify_signal_actionability(
            proposed_direction=best_proposal.proposed_decision,
            signal_tier=str(delta_signal.get("signal_tier", "REJECTED")),
            confidence=best_proposal.confidence,
            timeframe=timeframe,
            expected_net_edge_pct=float(exploration_gate.expected_net_edge_pct),
            expected_net_reward_risk=float(exploration_gate.expected_net_reward_risk),
        )
        symbol_session_entry_count = self._count_symbol_entries_in_current_experiment(symbol=symbol)
        critic = self._strategy_critic_agent.critique(
            proposal=best_proposal.as_dict(),
            total_cost_pct=float(cost_snapshot.minimum_profitable_move_pct),
            expected_net_edge_pct=float(exploration_gate.expected_net_edge_pct),
            expected_net_reward_risk=float(exploration_gate.expected_net_reward_risk),
            timeframe_alignment=tf_alignment.timeframe_alignment,
            contradiction_score=tf_alignment.contradiction_score,
            market_state=market_state.market_state,
            is_stale=assessment.is_stale and not allow_stale_fallback,
            gap_count=assessment.gap_count,
            duplicate_setup=duplicate_setup,
            loss_streak=risk_manager.loss_streak,
            data_quality_score=symbol_selection.data_quality_score,
        )
        meta_learning_preview = self._meta_learning_agent.assess(
            symbol=symbol,
            timeframe=timeframe,
            strategy_name=best_proposal.strategy_name,
            market_state=market_state.market_state,
            paper_mode="PAPER_EXPLORATION",
        )
        cooldown_state = self._symbol_cooldown_state(symbol=symbol, paper_mode="PAPER_EXPLORATION")
        paper_mode = self._select_paper_mode(
            observer_mode=observer_mode,
            assessment_is_stale=assessment.is_stale and not allow_stale_fallback,
            provider_used=provider_result.provider_used,
            symbol_tradable=symbol_selection.tradable_today,
            risk_manager_action=risk_manager.recommended_action,
            market_risk_mode=risk_manager.risk_mode,
            contradiction_score=tf_alignment.contradiction_score,
            alignment_label=tf_alignment.timeframe_alignment,
            meta_sample_strength=meta_learning_preview.sample_strength,
            open_positions=len(self._database.get_open_paper_positions()),
            recent_exploration_trades=self._recent_trade_count_by_mode("PAPER_EXPLORATION", hours=1),
            recent_rejected_opportunities=self._recent_rejection_count(symbol=symbol, timeframe=timeframe),
            has_positive_exploration_edge=exploration_gate.approved,
            has_positive_selective_edge=selective_gate.approved,
            symbol_has_open_trade=symbol_has_open_trade,
            symbol_in_cooldown=bool(cooldown_state["active"]),
            signal_actionability=signal_actionability,
            symbol_session_entry_count=symbol_session_entry_count,
        )
        meta_learning = self._meta_learning_agent.assess(
            symbol=symbol,
            timeframe=timeframe,
            strategy_name=best_proposal.strategy_name,
            market_state=market_state.market_state,
            paper_mode=paper_mode,
        )
        net_gate = exploration_gate if paper_mode == "PAPER_EXPLORATION" else selective_gate if paper_mode == "PAPER_SELECTIVE" else self._net_profitability_gate.evaluate(
            signal=delta_signal,
            cost_snapshot=cost_snapshot,
            risk_mode=risk_manager.risk_mode,
            paper_mode="OBSERVE_ONLY",
        )
        active_cost_snapshot = exploration_cost_snapshot if paper_mode == "PAPER_EXPLORATION" else cost_snapshot
        active_position_size = exploration_position_size if paper_mode == "PAPER_EXPLORATION" else selective_position_size
        delta_signal["paper_mode"] = paper_mode
        delta_signal["position_size_usd"] = active_position_size
        risk_reward = self._risk_reward_agent.evaluate(signal=delta_signal, cost_snapshot=active_cost_snapshot)
        would_trade_if_exploration_enabled = (
            best_proposal.proposed_decision in {"LONG", "SHORT"}
            and symbol_selection.tradable_today
            and risk_manager.recommended_action != "BLOCK"
            and critic.critic_decision != "REJECT"
            and exploration_gate.approved
            and signal_actionability != "NO_SIGNAL"
            and not (assessment.is_stale and not allow_stale_fallback)
            and not observer_mode
        )

        strategy_score = max(0.0, min(1.0, best_proposal.confidence))
        market_alignment_score = max(0.0, min(1.0, market_state.confidence))
        multi_timeframe_alignment_score = max(0.0, min(1.0, tf_alignment.alignment_score))
        economics_score = max(
            0.0,
            min(
                1.0,
                (
                    min(1.0, float(risk_reward.expected_net_reward_risk) / max(self._settings.paper_selective_min_rr, 0.000001))
                    + min(1.0, max(float(net_gate.expected_net_edge_pct), 0.0) / max(self._settings.min_expected_net_edge_pct, 0.000001))
                ) / 2.0,
            ),
        )
        score_breakdown = self._build_final_score_breakdown(
            strategy_score=strategy_score,
            market_alignment_score=market_alignment_score,
            multi_timeframe_alignment_score=multi_timeframe_alignment_score,
            economics_score=economics_score,
            data_quality_score=symbol_selection.data_quality_score,
            contradiction_score=tf_alignment.contradiction_score,
            cost_drag_pct=float(active_cost_snapshot.cost_drag_pct),
            critic_score=critic.critic_score,
            drawdown_pct=drawdown_pct,
            open_positions=len(self._database.get_open_paper_positions()),
            provider_used=provider_result.provider_used,
            paper_mode=paper_mode,
        )
        final_score = score_breakdown["final_score"]
        final_score_threshold = self._resolve_final_score_threshold(
            paper_mode=paper_mode,
            timeframe=timeframe,
            signal_actionability=signal_actionability,
            operating_horizon_minutes=operating_horizon_minutes,
        )
        approved = (
            best_proposal.proposed_decision in {"LONG", "SHORT"}
            and paper_mode != "OBSERVE_ONLY"
            and risk_manager.risk_mode != "DO_NOT_TRADE"
            and risk_manager.recommended_action != "BLOCK"
            and symbol_selection.tradable_today
            and not symbol_has_open_trade
            and not bool(cooldown_state["active"])
            and (
                symbol_session_entry_count < self._settings.exploration_max_entries_per_symbol_session
                if paper_mode == "PAPER_EXPLORATION"
                else True
            )
            and net_gate.approved
            and critic.critic_decision != "REJECT"
            and final_score >= final_score_threshold
            and (len(self._database.get_open_paper_positions()) < self._settings.exploration_max_open_positions if paper_mode == "PAPER_EXPLORATION" else True)
            and (self._recent_trade_count_by_mode("PAPER_EXPLORATION", hours=1) < self._settings.exploration_max_trades_per_hour if paper_mode == "PAPER_EXPLORATION" else True)
            and not (assessment.is_stale and not allow_stale_fallback)
            and not observer_mode
        )
        rejection_reason = ""
        rejected_by_agent = ""
        rejected_stage = ""
        near_approval = self._build_near_approval_snapshot(
            approved=approved,
            paper_mode=paper_mode,
            final_score=final_score,
            threshold=final_score_threshold,
            net_gate=net_gate,
            active_cost_snapshot=active_cost_snapshot,
            signal_actionability=signal_actionability,
            tf_alignment=tf_alignment,
            score_breakdown=score_breakdown,
            risk_manager=risk_manager,
            symbol_has_open_trade=symbol_has_open_trade,
            cooldown_state=cooldown_state,
            symbol_session_entry_count=symbol_session_entry_count,
            symbol_tradable=symbol_selection.tradable_today,
            stale_blocked=assessment.is_stale and not allow_stale_fallback,
            observer_mode=observer_mode,
        )
        if not approved:
            simple_reasons = self._build_simple_rejection_reasons(
                signal_actionability=signal_actionability,
                paper_mode=paper_mode,
                observer_mode=observer_mode,
                stale_blocked=assessment.is_stale and not allow_stale_fallback,
                symbol_tradable=symbol_selection.tradable_today,
                symbol_has_open_trade=symbol_has_open_trade,
                cooldown_state=cooldown_state,
                risk_manager=risk_manager,
                market_risk_mode=risk_manager.risk_mode,
                net_gate=net_gate,
                critic=critic,
                contradiction_score=tf_alignment.contradiction_score,
                alignment_label=tf_alignment.timeframe_alignment,
                final_score=final_score,
                threshold=final_score_threshold,
                open_positions=len(self._database.get_open_paper_positions()),
                symbol_session_entry_count=symbol_session_entry_count,
            )
            detailed_reasons = [
                self._paper_mode_reason(
                    paper_mode=paper_mode,
                    observer_mode=observer_mode,
                    assessment_is_stale=assessment.is_stale and not allow_stale_fallback,
                    provider_used=provider_result.provider_used,
                    symbol_tradable=symbol_selection.tradable_today,
                    contradiction_score=tf_alignment.contradiction_score,
                    risk_manager_action=risk_manager.recommended_action,
                    market_risk_mode=risk_manager.risk_mode,
                    exploration_gate=exploration_gate,
                    selective_gate=selective_gate,
                    symbol_has_open_trade=symbol_has_open_trade,
                    symbol_in_cooldown=bool(cooldown_state["active"]),
                    symbol_session_entry_count=symbol_session_entry_count,
                ),
                critic.rejection_reason or "",
                net_gate.reason if not net_gate.approved else "",
                risk_manager.reason if risk_manager.recommended_action == "BLOCK" else "",
                external_context_bias["reason"] if external_context_bias["news_used"] or external_context_bias["sentiment_used"] else "",
                f"final score {round(final_score, 4)} below minimum {round(final_score_threshold, 4)}" if final_score < final_score_threshold else "",
            ]
            rejection_reason = " | ".join(simple_reasons)
            rejected_by_agent, rejected_stage = self._classify_rejection(
                critic=critic,
                net_gate=net_gate,
                risk_manager=risk_manager,
                paper_mode=paper_mode,
                observer_mode=observer_mode,
                symbol_tradable=symbol_selection.tradable_today,
                final_score=final_score,
                threshold=final_score_threshold,
                signal_actionability=signal_actionability,
            )
        final_decision = best_proposal.proposed_decision if approved else "NO_TRADE"
        exit_reason = net_gate.close_condition if approved else rejection_reason or "no trade"

        payload = {
            "provider_used": provider_result.provider_used,
            "paper_mode": paper_mode,
            "paper_mode_reason": self._paper_mode_reason(
                paper_mode=paper_mode,
                observer_mode=observer_mode,
                assessment_is_stale=assessment.is_stale and not allow_stale_fallback,
                provider_used=provider_result.provider_used,
                symbol_tradable=symbol_selection.tradable_today,
                contradiction_score=tf_alignment.contradiction_score,
                risk_manager_action=risk_manager.recommended_action,
                market_risk_mode=risk_manager.risk_mode,
                exploration_gate=exploration_gate,
                selective_gate=selective_gate,
                symbol_has_open_trade=symbol_has_open_trade,
                symbol_in_cooldown=bool(cooldown_state["active"]),
                symbol_session_entry_count=symbol_session_entry_count,
            ),
            "operating_horizon_minutes": operating_horizon_minutes,
            "position_size_usd": active_position_size,
            "market_data": assessment.as_dict(),
            "features": feature_snapshot.as_dict(),
            "market_context": market_context,
            "market_state": market_state.as_dict(),
            "strategy_selection": selection.as_dict(),
            "best_proposal": best_proposal.as_dict(),
            "proposal_price_levels": {
                "stop_loss_price": proposal_stop_loss_price,
                "take_profit_price": proposal_take_profit_price,
            },
            "cost_snapshot": active_cost_snapshot.as_dict(),
            "exploration_cost_snapshot": exploration_cost_snapshot.as_dict(),
            "risk_reward": risk_reward.as_dict(),
            "net_gate": net_gate.as_dict(),
            "exploration_gate": exploration_gate.as_dict(),
            "selective_gate": selective_gate.as_dict(),
            "external_context": external_context_bias,
            "critic": critic.as_dict(),
            "risk_manager": risk_manager.as_dict(),
            "meta_learning": meta_learning.as_dict(),
            "similar_trade_stats": similar_trade_stats,
            "timeframe_alignment": tf_alignment.as_dict(),
            "rejection_diagnostics": {
                "rejected_by_agent": rejected_by_agent,
                "rejected_stage": rejected_stage,
                "would_trade_if_exploration_enabled": would_trade_if_exploration_enabled,
                "signal_actionability": signal_actionability,
                "simple_reasons": simple_reasons if not approved else [],
                "primary_reason": simple_reasons[0] if not approved and simple_reasons else "",
                "secondary_reason": simple_reasons[1] if not approved and len(simple_reasons) > 1 else "",
                "detailed_reasons": [reason for reason in detailed_reasons if reason] if not approved else [],
                "near_approval": near_approval,
                "symbol_session_entry_count": symbol_session_entry_count,
            },
            "score_breakdown": score_breakdown,
        }

        for proposal in proposals:
            approved_vote = proposal.agent_name == best_proposal.agent_name and approved
            self._database.insert_strategy_vote(
                StrategyVoteRecord(
                    timestamp=timestamp,
                    symbol=symbol,
                    timeframe=timeframe,
                    agent_name=proposal.agent_name,
                    strategy_name=proposal.strategy_name,
                    decision=proposal.proposed_decision,
                    confidence=proposal.confidence,
                    score=proposal.confidence,
                    expected_move_pct=proposal.expected_move_pct,
                    expected_net_edge_pct=proposal.expected_net_edge_pct,
                    cost_estimate_pct=active_cost_snapshot.minimum_profitable_move_pct,
                    risk_reward_ratio=proposal.risk_reward_ratio,
                    regime=market_state.market_state,
                    risk_mode=risk_manager.risk_mode,
                    approved=approved_vote,
                    rejection_reason=None if approved_vote else rejection_reason or critic.rejection_reason,
                    raw_payload=json.dumps(proposal.as_dict(), ensure_ascii=True),
                )
            )

        self._database.insert_brain_decision(
            BrainDecisionRecord(
                timestamp=timestamp,
                symbol=symbol,
                timeframe=timeframe,
                final_decision=final_decision,
                final_score=round(final_score, 6),
                market_state=market_state.market_state,
                selected_strategy=best_proposal.strategy_name,
                risk_mode=risk_manager.risk_mode,
                expected_net_edge_pct=float(net_gate.expected_net_edge_pct),
                risk_reward_ratio=float(net_gate.expected_net_reward_risk),
                cost_coverage_multiple=float(net_gate.cost_coverage_multiple),
                approved=approved,
                reason=rejection_reason or best_proposal.entry_reason,
                provider_used=provider_result.provider_used,
                paper_mode=paper_mode,
                rejected_by_agent=rejected_by_agent or None,
                rejected_stage=rejected_stage or None,
                outcome_label=None,
                expected_move_pct=float(best_proposal.expected_move_pct),
                total_cost_pct=float(active_cost_snapshot.minimum_profitable_move_pct),
                multi_timeframe_conflict=tf_alignment.timeframe_alignment == "CONTRADICTED",
                would_trade_if_exploration_enabled=would_trade_if_exploration_enabled,
                raw_payload=json.dumps(payload, ensure_ascii=True),
            )
        )
        if not approved:
            self._database.insert_rejected_signal(
                RejectedSignalRecord(
                    symbol=symbol,
                    timeframe=timeframe,
                    signal_tier=str(delta_signal.get("signal_tier", "REJECTED")),
                    reason=rejection_reason or best_proposal.entry_reason,
                    context_payload=json.dumps(payload, ensure_ascii=True),
                    thresholds_failed=json.dumps(list(delta_signal.get("thresholds_failed", [])), ensure_ascii=True),
                    timestamp=timestamp,
                    rejected_by_agent=rejected_by_agent or None,
                    rejected_stage=rejected_stage or None,
                    expected_move_pct=float(best_proposal.expected_move_pct),
                    total_cost_pct=float(active_cost_snapshot.minimum_profitable_move_pct),
                    expected_net_edge_pct=float(net_gate.expected_net_edge_pct),
                    risk_reward_ratio=float(net_gate.expected_net_reward_risk),
                    cost_coverage_multiple=float(net_gate.cost_coverage_multiple),
                    multi_timeframe_conflict=tf_alignment.timeframe_alignment == "CONTRADICTED",
                    market_regime=market_state.market_state,
                    selected_strategy=best_proposal.strategy_name,
                    paper_mode=paper_mode,
                    would_trade_if_exploration_enabled=would_trade_if_exploration_enabled,
                )
            )
        self._database.insert_agent_decision(
            AgentDecisionRecord(
                timestamp=timestamp,
                agent_name="TradingBrainOrchestrator",
                symbol=symbol,
                timeframe=timeframe,
                decision=final_decision,
                confidence=round(max(0.0, min(1.0, best_proposal.confidence + meta_learning.confidence_adjustment - (score_breakdown["critic_penalty"] * 0.5))), 6),
                inputs_used=json.dumps(
                    {
                        "provider": provider_result.provider_used,
                        "strategy": best_proposal.strategy_name,
                        "market_state": market_state.market_state,
                        "risk_mode": risk_manager.risk_mode,
                    },
                    ensure_ascii=True,
                ),
                reasoning_summary=rejection_reason or best_proposal.entry_reason,
                linked_signal_id=None,
                linked_trade_id=None,
                provider_used=provider_result.provider_used,
                outcome_label="APPROVED" if approved else "REJECTED",
            )
        )
        self._evaluate_pending_no_trade_outcomes()

        return BrainDecision(
            symbol=symbol,
            timeframe=timeframe,
            final_decision=final_decision,
            selected_strategy=best_proposal.strategy_name,
            market_state=market_state.market_state,
            risk_mode=risk_manager.risk_mode,
            confidence=round(max(0.0, min(1.0, best_proposal.confidence + meta_learning.confidence_adjustment - (score_breakdown["critic_penalty"] * 0.5))), 6),
            final_score=round(final_score, 6),
            expected_move_pct=float(best_proposal.expected_move_pct),
            total_cost_pct=float(cost_snapshot.minimum_profitable_move_pct),
            expected_net_edge_pct=float(net_gate.expected_net_edge_pct),
            risk_reward_ratio=float(net_gate.expected_net_reward_risk),
            cost_coverage_multiple=float(net_gate.cost_coverage_multiple),
            approved=approved,
            rejection_reason=rejection_reason,
            entry_reason=best_proposal.entry_reason,
            exit_reason=exit_reason,
            provider_used=provider_result.provider_used,
            data_stale=assessment.is_stale,
            paper_mode=paper_mode,
            raw_payload=payload,
        )

    def _build_external_context_bias(self, *, symbol: str, direction: str) -> dict[str, object]:
        bias = build_symbol_context_bias(
            database=self._database,
            symbol=symbol,
            direction=direction,
        )
        bias["reason"] = (
            f"external_context news_used={bias['news_used']} sentiment_used={bias['sentiment_used']} "
            f"news_conflict={bias['news_conflict']} risk_event={bias['risk_event']} "
            f"confidence_adjustment={bias['confidence_adjustment']}"
        )
        return bias

    @staticmethod
    def _apply_external_context_to_proposal(
        *,
        proposal: StrategyProposal,
        external_context_bias: dict[str, object],
    ) -> StrategyProposal:
        if proposal.proposed_decision not in {"LONG", "SHORT"}:
            return proposal
        adjusted_confidence = max(
            0.0,
            min(1.0, proposal.confidence + float(external_context_bias.get("confidence_adjustment", 0.0))),
        )
        extra_flags = list(proposal.risk_flags)
        if external_context_bias.get("news_conflict"):
            extra_flags.append("news_conflict")
        if external_context_bias.get("risk_event"):
            extra_flags.append("external_risk_event")
        return replace(
            proposal,
            confidence=round(adjusted_confidence, 6),
            entry_reason=proposal.entry_reason + f" | {external_context_bias['reason']}",
            risk_flags=tuple(dict.fromkeys(extra_flags)),
            raw_payload={**proposal.raw_payload, "external_context": external_context_bias},
        )

    @staticmethod
    def _apply_external_context_to_risk_manager(
        *,
        risk_manager,
        external_context_bias: dict[str, object],
    ):
        if not external_context_bias.get("risk_event") and not external_context_bias.get("news_conflict"):
            return risk_manager
        adjusted_risk_mode = risk_manager.risk_mode
        adjusted_action = risk_manager.recommended_action
        if external_context_bias.get("news_conflict"):
            if adjusted_risk_mode == "BALANCED":
                adjusted_risk_mode = "CONSERVATIVE"
            elif adjusted_risk_mode == "AGGRESSIVE":
                adjusted_risk_mode = "BALANCED"
        if external_context_bias.get("risk_event") and adjusted_risk_mode not in {"DO_NOT_TRADE", "CAPITAL_PROTECTION"}:
            adjusted_risk_mode = "CONSERVATIVE"
        return replace(
            risk_manager,
            risk_mode=adjusted_risk_mode,
            recommended_action=adjusted_action,
            reason=risk_manager.reason + f"; {external_context_bias['reason']}",
        )

    @staticmethod
    def _apply_external_context_to_alignment(
        *,
        alignment: TimeframeAlignment,
        external_context_bias: dict[str, object],
    ) -> TimeframeAlignment:
        contradiction_penalty = float(external_context_bias.get("contradiction_penalty", 0.0))
        if contradiction_penalty <= 0:
            return alignment
        adjusted_contradiction = min(1.0, alignment.contradiction_score + contradiction_penalty)
        adjusted_alignment = max(0.0, alignment.alignment_score - (contradiction_penalty * 0.35))
        return replace(
            alignment,
            contradiction_score=round(adjusted_contradiction, 6),
            alignment_score=round(adjusted_alignment, 6),
            final_timeframe_reason=alignment.final_timeframe_reason + f" {external_context_bias['reason']}",
        )

    def _collect_strategy_proposals(
        self,
        *,
        symbol: str,
        timeframe: str,
        features: dict[str, object],
        market_state: dict[str, object],
        direction_bias: str,
        selection,
    ) -> list[StrategyProposal]:
        proposals: list[StrategyProposal] = []
        names = {selection.primary_strategy, selection.secondary_strategy}
        if timeframe in self._settings.execution_timeframes and direction_bias in {"LONG", "SHORT"}:
            names.update({"TREND_FOLLOWING", "PULLBACK_CONTINUATION"})
        for strategy_name in names:
            if strategy_name in {"NO_TRADE", ""}:
                continue
            agent = self._strategy_agents.get(strategy_name)
            if agent is None:
                continue
            proposal = agent.evaluate(symbol=symbol, timeframe=timeframe, features=features, market_state=market_state, direction_bias=direction_bias)
            proposals.append(
                self._normalize_strategy_proposal(
                    proposal=proposal,
                    features=features,
                    timeframe=timeframe,
                    direction_bias=direction_bias,
                )
            )
        if not any(item.proposed_decision in {"LONG", "SHORT"} for item in proposals):
            fallback = self._build_intraday_fallback_proposal(
                symbol=symbol,
                timeframe=timeframe,
                features=features,
                market_state=market_state,
                direction_bias=direction_bias,
            )
            if fallback is not None:
                proposals.append(fallback)
        if not proposals:
            proposals.append(
                StrategyProposal(
                    agent_name="NoStrategy",
                    strategy_name="NO_TRADE",
                    symbol=symbol,
                    timeframe=timeframe,
                    proposed_decision="NO_TRADE",
                    confidence=0.0,
                    expected_move_pct=0.0,
                    stop_loss_pct=0.0,
                    take_profit_pct=0.0,
                    risk_reward_ratio=0.0,
                    expected_net_edge_pct=0.0,
                    entry_reason="no strategy was eligible",
                    invalidation_reason="no setup",
                    risk_flags=("no_strategy",),
                    raw_payload={},
                )
            )
        return proposals

    def _normalize_strategy_proposal(
        self,
        *,
        proposal: StrategyProposal,
        features: dict[str, object],
        timeframe: str,
        direction_bias: str,
    ) -> StrategyProposal:
        if proposal.proposed_decision not in {"LONG", "SHORT"}:
            return proposal
        atr_pct = max(float(features.get("atr_pct", 0.0)), 0.0)
        avg_range_pct = max(float(features.get("avg_range_pct", 0.0)), 0.0)
        roc = abs(float(features.get("roc", 0.0)))
        acceleration = abs(float(features.get("acceleration", 0.0)))
        distance_ema9 = abs(float(features.get("distance_to_ema_9_pct", 0.0)))
        distance_ema21 = abs(float(features.get("distance_to_ema_21_pct", 0.0)))
        candle_strength = abs(float(features.get("candle_strength", 0.0)))
        relative_volume = max(float(features.get("relative_volume", 0.0)), 0.0)
        break_even_move_pct = max(float(features.get("break_even_move_pct", 0.0)), 0.0)
        required_net_move_pct = max(float(features.get("required_net_move_pct", 0.0)), break_even_move_pct)
        profile = self._timeframe_trade_profile(timeframe)
        intraday_floor = float(profile["target_floor"])
        momentum_component = max(
            (roc * float(profile["roc_weight"])),
            (acceleration * float(profile["acceleration_weight"])),
            (candle_strength * float(profile["candle_weight"])),
            0.0,
        )
        swing_component = max(
            (atr_pct * float(profile["atr_swing_weight"])),
            (avg_range_pct * float(profile["range_swing_weight"])),
            (distance_ema9 * float(profile["ema9_weight"])),
            (distance_ema21 * float(profile["ema21_weight"])),
            0.0,
        )
        liquidity_boost = 1.08 if relative_volume >= 1.2 else 1.0
        tactical_target_component = max(
            swing_component * liquidity_boost * float(profile["liquidity_swing_multiplier"]),
            momentum_component + (swing_component * float(profile["momentum_swing_mix"])),
            atr_pct * float(profile["atr_target_multiplier"]),
            avg_range_pct * float(profile["range_target_multiplier"]),
            0.0,
        )
        stop_loss_pct = max(
            float(proposal.stop_loss_pct),
            atr_pct * float(profile["stop_atr_multiplier"]),
            avg_range_pct * float(profile["stop_range_multiplier"]),
            break_even_move_pct * float(profile["break_even_stop_multiplier"]),
            float(profile["stop_floor"]),
        )
        desired_net_rr = float(profile["desired_net_rr"])
        minimum_rr_target_pct = break_even_move_pct + ((stop_loss_pct + break_even_move_pct) * desired_net_rr)
        expected_move_pct = max(
            float(proposal.expected_move_pct),
            tactical_target_component,
            required_net_move_pct * float(profile["required_move_multiplier"]),
            minimum_rr_target_pct,
            intraday_floor,
        )
        take_profit_pct = max(
            float(proposal.take_profit_pct),
            expected_move_pct,
            stop_loss_pct * float(profile["take_profit_stop_multiplier"]),
            required_net_move_pct * float(profile["required_move_multiplier"]),
            minimum_rr_target_pct,
        )
        risk_reward_ratio = take_profit_pct / max(stop_loss_pct, 0.000001)
        expected_net_edge_pct = max(take_profit_pct - break_even_move_pct, 0.0)
        expected_net_reward_risk = expected_net_edge_pct / max(stop_loss_pct + break_even_move_pct, 0.000001)
        confidence_boost = float(profile["confidence_boost"]) if proposal.proposed_decision == direction_bias and expected_move_pct > required_net_move_pct else 0.0
        return replace(
            proposal,
            confidence=round(max(0.0, min(1.0, proposal.confidence + confidence_boost)), 6),
            expected_move_pct=round(expected_move_pct, 6),
            stop_loss_pct=round(stop_loss_pct, 6),
            take_profit_pct=round(take_profit_pct, 6),
            risk_reward_ratio=round(risk_reward_ratio, 6),
            expected_net_edge_pct=round(expected_net_edge_pct, 6),
            raw_payload={
                **proposal.raw_payload,
                "normalized_by_orchestrator": True,
                "break_even_move_pct": round(break_even_move_pct, 6),
                "required_net_move_pct": round(required_net_move_pct, 6),
                "momentum_component": round(momentum_component, 6),
                "swing_component": round(swing_component, 6),
                "tactical_target_component": round(tactical_target_component, 6),
                "minimum_rr_target_pct": round(minimum_rr_target_pct, 6),
                "desired_net_rr": round(desired_net_rr, 6),
                "expected_net_reward_risk_from_proposal": round(expected_net_reward_risk, 6),
                "timeframe_trade_profile": dict(profile),
            },
        )

    def _build_intraday_fallback_proposal(
        self,
        *,
        symbol: str,
        timeframe: str,
        features: dict[str, object],
        market_state: dict[str, object],
        direction_bias: str,
    ) -> StrategyProposal | None:
        if timeframe not in self._settings.execution_timeframes or direction_bias not in {"LONG", "SHORT"}:
            return None
        atr_pct = max(float(features.get("atr_pct", 0.0)), 0.0)
        roc = float(features.get("roc", 0.0))
        acceleration = float(features.get("acceleration", 0.0))
        relative_volume = float(features.get("relative_volume", 0.0))
        rsi = float(features.get("rsi", 50.0))
        candle_strength = float(features.get("candle_strength", 0.0))
        distance_ema9 = float(features.get("distance_to_ema_9_pct", 0.0))
        structure = str(features.get("structure", "UNKNOWN"))
        trend_state = str(market_state.get("trend_state", "SIDEWAYS"))
        long_ok = (
            direction_bias == "LONG"
            and trend_state == "UP"
            and rsi >= 45
            and (roc >= -0.02 or acceleration >= 0 or distance_ema9 <= 0.08)
        )
        short_ok = (
            direction_bias == "SHORT"
            and trend_state == "DOWN"
            and rsi <= 55
            and (roc <= 0.02 or acceleration <= 0 or distance_ema9 >= -0.08)
        )
        profile = self._timeframe_trade_profile(timeframe)
        structure_present = (
            atr_pct >= float(profile["fallback_atr_floor"])
            or abs(roc) >= float(profile["fallback_roc_floor"])
            or abs(candle_strength) >= float(profile["fallback_candle_floor"])
            or relative_volume >= float(profile["fallback_volume_floor"])
        )
        if not structure_present or not (long_ok or short_ok):
            return None
        strategy_name = "PULLBACK_CONTINUATION" if abs(distance_ema9) >= 0.05 else "TREND_FOLLOWING"
        agent_name = "PullbackContinuationAgent" if strategy_name == "PULLBACK_CONTINUATION" else "TrendFollowingAgent"
        proposal = StrategyProposal(
            agent_name=agent_name,
            strategy_name=strategy_name,
            symbol=symbol,
            timeframe=timeframe,
            proposed_decision=direction_bias,
            confidence=0.56 if relative_volume < 1.0 else 0.62,
            expected_move_pct=0.0,
            stop_loss_pct=0.0,
            take_profit_pct=0.0,
            risk_reward_ratio=0.0,
            expected_net_edge_pct=0.0,
            entry_reason=f"structural fallback sees {trend_state} with usable 15m pullback structure {structure}",
            invalidation_reason="fallback structure no longer supports the tactical direction",
            risk_flags=("intraday_fallback",),
            raw_payload={"fallback": True, "structure": structure, "rsi": rsi, "relative_volume": relative_volume},
        )
        return self._normalize_strategy_proposal(
            proposal=proposal,
            features=features,
            timeframe=timeframe,
            direction_bias=direction_bias,
        )

    @staticmethod
    def _proposal_price_levels(
        *,
        entry_price: float,
        direction: str,
        proposal: StrategyProposal,
    ) -> tuple[float | None, float | None]:
        if entry_price <= 0 or direction not in {"LONG", "SHORT"}:
            return None, None
        stop_loss_pct = max(float(proposal.stop_loss_pct), 0.0)
        take_profit_pct = max(float(proposal.take_profit_pct), 0.0)
        if stop_loss_pct <= 0 or take_profit_pct <= 0:
            return None, None
        if direction == "SHORT":
            stop_loss_price = entry_price * (1 + (stop_loss_pct / 100))
            take_profit_price = entry_price * (1 - (take_profit_pct / 100))
        else:
            stop_loss_price = entry_price * (1 - (stop_loss_pct / 100))
            take_profit_price = entry_price * (1 + (take_profit_pct / 100))
        return round(stop_loss_price, 8), round(take_profit_price, 8)

    @staticmethod
    def _timeframe_trade_profile(timeframe: str) -> dict[str, float]:
        if timeframe == "15m":
            return {
                "target_floor": 0.85,
                "stop_floor": 0.18,
                "desired_net_rr": 1.35,
                "roc_weight": 4.2,
                "acceleration_weight": 2.8,
                "candle_weight": 1.55,
                "atr_swing_weight": 1.7,
                "range_swing_weight": 1.35,
                "ema9_weight": 2.5,
                "ema21_weight": 2.0,
                "liquidity_swing_multiplier": 1.3,
                "momentum_swing_mix": 0.78,
                "atr_target_multiplier": 2.85,
                "range_target_multiplier": 1.95,
                "stop_atr_multiplier": 0.92,
                "stop_range_multiplier": 0.74,
                "break_even_stop_multiplier": 0.5,
                "required_move_multiplier": 1.55,
                "take_profit_stop_multiplier": 1.7,
                "confidence_boost": 0.04,
                "fallback_atr_floor": 0.12,
                "fallback_roc_floor": 0.08,
                "fallback_candle_floor": 0.03,
                "fallback_volume_floor": 0.95,
            }
        if timeframe == "30m":
            return {
                "target_floor": 1.15,
                "stop_floor": 0.24,
                "desired_net_rr": 1.5,
                "roc_weight": 4.4,
                "acceleration_weight": 3.0,
                "candle_weight": 1.6,
                "atr_swing_weight": 1.9,
                "range_swing_weight": 1.45,
                "ema9_weight": 2.7,
                "ema21_weight": 2.15,
                "liquidity_swing_multiplier": 1.34,
                "momentum_swing_mix": 0.82,
                "atr_target_multiplier": 3.05,
                "range_target_multiplier": 2.1,
                "stop_atr_multiplier": 0.95,
                "stop_range_multiplier": 0.78,
                "break_even_stop_multiplier": 0.48,
                "required_move_multiplier": 1.62,
                "take_profit_stop_multiplier": 1.78,
                "confidence_boost": 0.04,
                "fallback_atr_floor": 0.14,
                "fallback_roc_floor": 0.09,
                "fallback_candle_floor": 0.035,
                "fallback_volume_floor": 0.98,
            }
        if timeframe in {"1h", "4h"}:
            return {
                "target_floor": 1.45,
                "stop_floor": 0.32,
                "desired_net_rr": 1.6,
                "roc_weight": 4.6,
                "acceleration_weight": 3.1,
                "candle_weight": 1.65,
                "atr_swing_weight": 2.1,
                "range_swing_weight": 1.55,
                "ema9_weight": 2.85,
                "ema21_weight": 2.25,
                "liquidity_swing_multiplier": 1.36,
                "momentum_swing_mix": 0.86,
                "atr_target_multiplier": 3.25,
                "range_target_multiplier": 2.2,
                "stop_atr_multiplier": 1.0,
                "stop_range_multiplier": 0.82,
                "break_even_stop_multiplier": 0.46,
                "required_move_multiplier": 1.7,
                "take_profit_stop_multiplier": 1.85,
                "confidence_boost": 0.04,
                "fallback_atr_floor": 0.16,
                "fallback_roc_floor": 0.1,
                "fallback_candle_floor": 0.04,
                "fallback_volume_floor": 1.0,
            }
        if timeframe == "5m":
            return {
                "target_floor": 0.28,
                "stop_floor": 0.1,
                "desired_net_rr": 1.15,
                "roc_weight": 3.1,
                "acceleration_weight": 2.1,
                "candle_weight": 1.2,
                "atr_swing_weight": 1.45,
                "range_swing_weight": 1.1,
                "ema9_weight": 2.2,
                "ema21_weight": 1.7,
                "liquidity_swing_multiplier": 1.2,
                "momentum_swing_mix": 0.55,
                "atr_target_multiplier": 2.0,
                "range_target_multiplier": 1.45,
                "stop_atr_multiplier": 0.75,
                "stop_range_multiplier": 0.6,
                "break_even_stop_multiplier": 0.55,
                "required_move_multiplier": 1.35,
                "take_profit_stop_multiplier": 1.45,
                "confidence_boost": 0.03,
                "fallback_atr_floor": 0.08,
                "fallback_roc_floor": 0.03,
                "fallback_candle_floor": 0.015,
                "fallback_volume_floor": 0.85,
            }
        if timeframe == "3m":
            return {
                "target_floor": 0.22,
                "stop_floor": 0.08,
                "desired_net_rr": 1.05,
                "roc_weight": 3.1,
                "acceleration_weight": 2.1,
                "candle_weight": 1.2,
                "atr_swing_weight": 1.45,
                "range_swing_weight": 1.1,
                "ema9_weight": 2.2,
                "ema21_weight": 1.7,
                "liquidity_swing_multiplier": 1.2,
                "momentum_swing_mix": 0.55,
                "atr_target_multiplier": 2.0,
                "range_target_multiplier": 1.45,
                "stop_atr_multiplier": 0.75,
                "stop_range_multiplier": 0.6,
                "break_even_stop_multiplier": 0.55,
                "required_move_multiplier": 1.35,
                "take_profit_stop_multiplier": 1.45,
                "confidence_boost": 0.03,
                "fallback_atr_floor": 0.08,
                "fallback_roc_floor": 0.03,
                "fallback_candle_floor": 0.015,
                "fallback_volume_floor": 0.85,
            }
        return {
            "target_floor": 0.14,
            "stop_floor": 0.06,
            "desired_net_rr": 0.95,
            "roc_weight": 3.1,
            "acceleration_weight": 2.1,
            "candle_weight": 1.2,
            "atr_swing_weight": 1.45,
            "range_swing_weight": 1.1,
            "ema9_weight": 2.2,
            "ema21_weight": 1.7,
            "liquidity_swing_multiplier": 1.2,
            "momentum_swing_mix": 0.55,
            "atr_target_multiplier": 2.0,
            "range_target_multiplier": 1.45,
            "stop_atr_multiplier": 0.75,
            "stop_range_multiplier": 0.6,
            "break_even_stop_multiplier": 0.55,
            "required_move_multiplier": 1.35,
            "take_profit_stop_multiplier": 1.45,
            "confidence_boost": 0.03,
            "fallback_atr_floor": 0.08,
            "fallback_roc_floor": 0.03,
            "fallback_candle_floor": 0.015,
            "fallback_volume_floor": 0.85,
        }

    def _relax_intraday_risk_manager(
        self,
        *,
        risk_manager,
        market_state: dict[str, object],
        best_proposal: StrategyProposal,
        timeframe: str,
        provider_used: str,
        assessment_is_stale: bool,
        symbol_tradable: bool,
        data_quality_score: float,
        alignment: TimeframeAlignment,
        operating_horizon_minutes: int | None,
    ):
        short_intraday_run = operating_horizon_minutes is not None and operating_horizon_minutes <= 60
        if not short_intraday_run:
            return risk_manager
        if provider_used != "BINANCE" or assessment_is_stale or not symbol_tradable or data_quality_score < 0.6:
            return risk_manager
        if best_proposal.proposed_decision not in {"LONG", "SHORT"}:
            return risk_manager
        if risk_manager.recommended_action == "BLOCK" or risk_manager.risk_mode != "DO_NOT_TRADE":
            return risk_manager
        if alignment.timeframe_alignment == "CONTRADICTED" or alignment.contradiction_score >= 0.75:
            return risk_manager
        if str(market_state.get("market_state", "UNKNOWN")) not in {"UNKNOWN", "LOW_VOLATILITY", "RANGE"}:
            return risk_manager
        return replace(
            risk_manager,
            risk_mode="CONSERVATIVE",
            recommended_action="ALLOW",
            position_size_pct=max(float(risk_manager.position_size_pct), 0.04),
            reason=risk_manager.reason + "; intraday exploration override converted DO_NOT_TRADE into CONSERVATIVE on fresh short-run data",
        )

    def _build_timeframe_contexts(
        self,
        *,
        symbol: str,
        execution_timeframe: str,
        current_context: dict[str, object],
        operating_horizon_minutes: int | None,
        prefer_fallback: bool,
    ) -> dict[str, dict[str, object]]:
        contexts: dict[str, dict[str, object]] = {execution_timeframe: current_context}
        allowed_contexts = list(dict.fromkeys((*self._settings.context_timeframes, *self._settings.structural_timeframes)))
        for timeframe in allowed_contexts:
            provider_result = self._provider_router.fetch_latest_closed_candles(
                symbol=symbol,
                timeframe=timeframe,
                limit=max(self._settings.feature_store_lookback, 20),
                prefer_fallback=prefer_fallback,
            )
            for candle in provider_result.candles:
                self._database.insert_candles([candle])
            candles = self._database.get_recent_candles(symbol=symbol, timeframe=timeframe, limit=20)
            if len(candles) < 5:
                continue
            contexts[timeframe] = self._market_context_agent.evaluate(symbol=symbol, timeframe=timeframe, candles=candles)
        return contexts

    def _loss_streak(self) -> int:
        streak = 0
        for trade in self._database.get_recent_simulated_trades(limit=20):
            if trade.status == "OPEN":
                continue
            if trade.outcome in {"LOSS_NET", "GROSS_LOSS_NET_LOSS", "GROSS_WIN_NET_LOSS", "WIN_GROSS_ONLY_NET_LOSS", "COST_KILLED_TRADE"}:
                streak += 1
            else:
                break
        return streak

    def _is_duplicate_setup(self, *, symbol: str, timeframe: str, direction: str, setup_signature: str) -> bool:
        for trade in self._database.get_open_simulated_trades():
            if trade.symbol == symbol and trade.timeframe == timeframe and trade.direction == direction and (trade.setup_signature or "") == setup_signature:
                return True
        return False

    def _recent_trade_count_by_mode(self, paper_mode: str, *, hours: int) -> int:
        cutoff = datetime.now(timezone.utc).timestamp() - (hours * 3600)
        count = 0
        for trade in self._database.get_recent_simulated_trades(limit=200):
            timestamp_value = trade.created_at or trade.entry_time
            if not timestamp_value:
                continue
            try:
                trade_ts = datetime.fromisoformat(timestamp_value).timestamp()
            except ValueError:
                continue
            if trade_ts >= cutoff and (trade.paper_mode or "OBSERVE_ONLY") == paper_mode:
                count += 1
        return count

    def _recent_rejection_count(self, *, symbol: str, timeframe: str) -> int:
        count = 0
        for row in self._database.get_recent_rejected_signals(limit=100):
            if row.get("symbol") == symbol and row.get("timeframe") == timeframe:
                count += 1
        return count

    def _has_open_trade_for_symbol(self, *, symbol: str) -> bool:
        return any(trade.symbol == symbol for trade in self._database.get_open_simulated_trades())

    def _count_symbol_entries_in_current_experiment(self, *, symbol: str) -> int:
        current_experiment = self._database.get_current_paper_experiment() or self._database.get_latest_paper_experiment()
        experiment_id = int(current_experiment["id"]) if current_experiment else None
        return sum(
            1
            for trade in self._database.get_recent_simulated_trades(limit=300, experiment_id=experiment_id)
            if trade.symbol == symbol
        )

    def _symbol_cooldown_state(self, *, symbol: str, paper_mode: str) -> dict[str, object]:
        cooldown_minutes = (
            self._settings.exploration_symbol_cooldown_minutes
            if paper_mode == "PAPER_EXPLORATION"
            else self._settings.selective_symbol_cooldown_minutes
        )
        now_ts = datetime.now(timezone.utc).timestamp()
        cutoff = now_ts - (cooldown_minutes * 60)
        for trade in self._database.get_recent_simulated_trades(limit=100):
            if trade.symbol != symbol or trade.status == "OPEN":
                continue
            realized = trade.final_net_pnl_after_all_costs if trade.final_net_pnl_after_all_costs is not None else (
                trade.net_pnl if trade.net_pnl is not None else (trade.pnl or 0.0)
            )
            if realized >= 0:
                continue
            timestamp_value = trade.exit_time or trade.updated_at or trade.entry_time
            if not timestamp_value:
                continue
            try:
                trade_ts = datetime.fromisoformat(timestamp_value).timestamp()
            except ValueError:
                continue
            if trade_ts >= cutoff:
                cooldown_expiry = trade_ts + (cooldown_minutes * 60)
                remaining_minutes = max(0, int((cooldown_expiry - now_ts) / 60))
                return {
                    "active": True,
                    "cooldown_minutes": cooldown_minutes,
                    "remaining_minutes": remaining_minutes,
                    "trade_id": trade.id,
                }
        return {
            "active": False,
            "cooldown_minutes": cooldown_minutes,
            "remaining_minutes": 0,
            "trade_id": None,
        }

    def _classify_signal_actionability(
        self,
        *,
        proposed_direction: str,
        signal_tier: str,
        confidence: float,
        timeframe: str,
        expected_net_edge_pct: float,
        expected_net_reward_risk: float,
    ) -> str:
        if proposed_direction not in {"LONG", "SHORT"}:
            return "NO_SIGNAL"
        if timeframe not in self._settings.execution_timeframes:
            return "NO_SIGNAL"
        if timeframe == "15m":
            if signal_tier in {"STRONG"}:
                return "VALID_STRONG"
            if signal_tier == "MEDIUM":
                return "VALID_NON_SELECTIVE"
            if signal_tier == "WEAK":
                return "VALID_NON_SELECTIVE" if confidence >= 0.5 and expected_net_edge_pct > 0 and expected_net_reward_risk >= 1.0 else "WEAK_EXPLORABLE"
            if signal_tier in {"NONE", "UNKNOWN"}:
                return "VALID_NON_SELECTIVE" if confidence >= 0.5 and expected_net_edge_pct > 0 and expected_net_reward_risk >= 1.0 else "NO_SIGNAL"
            if signal_tier == "REJECTED":
                return "WEAK_EXPLORABLE" if confidence >= 0.52 and expected_net_edge_pct > 0 and expected_net_reward_risk >= 1.05 else "NO_SIGNAL"
            return "WEAK_EXPLORABLE" if confidence >= 0.48 and expected_net_edge_pct > 0 and expected_net_reward_risk >= 1.0 else "NO_SIGNAL"
        intraday_execution_timeframe = timeframe in {"1m", "3m", "5m"}
        if signal_tier == "REJECTED":
            if confidence >= 0.46:
                return "WEAK_EXPLORABLE"
            if intraday_execution_timeframe and confidence >= 0.38 and expected_net_edge_pct > 0 and expected_net_reward_risk >= 0.72:
                return "WEAK_EXPLORABLE"
            return "NO_SIGNAL"
        if signal_tier in {"NONE", "UNKNOWN"}:
            if intraday_execution_timeframe and confidence >= 0.42 and expected_net_edge_pct > 0 and expected_net_reward_risk >= 0.8:
                return "WEAK_EXPLORABLE"
            return "NO_SIGNAL"
        if signal_tier == "WEAK":
            return "WEAK_EXPLORABLE"
        if signal_tier == "MEDIUM":
            return "VALID_NON_SELECTIVE"
        return "VALID_STRONG"

    @staticmethod
    def _build_simple_rejection_reasons(
        *,
        signal_actionability: str,
        paper_mode: str,
        observer_mode: bool,
        stale_blocked: bool,
        symbol_tradable: bool,
        symbol_has_open_trade: bool,
        cooldown_state: dict[str, object],
        risk_manager,
        market_risk_mode: str,
        net_gate,
        critic,
        contradiction_score: float,
        alignment_label: str,
        final_score: float,
        threshold: float,
        open_positions: int,
        symbol_session_entry_count: int,
    ) -> list[str]:
        simple_reasons: list[str] = []
        if signal_actionability == "NO_SIGNAL":
            simple_reasons.append("signal_not_actionable")
        if stale_blocked:
            simple_reasons.append("stale_data")
        if "poor_data_quality" in critic.penalties_applied or "severe_gaps" in critic.penalties_applied:
            simple_reasons.append("poor_data_quality")
        if (
            alignment_label == "CONTRADICTED"
            or contradiction_score >= 0.75
            or "critical_contradiction_score" in critic.penalties_applied
            or "high_contradiction_score" in critic.penalties_applied
        ):
            simple_reasons.append("multi_timeframe_contradiction")
        if market_risk_mode == "CAPITAL_PROTECTION" or risk_manager.risk_mode == "CAPITAL_PROTECTION":
            simple_reasons.append("risk_too_high_capital_protection")
        if any("net reward/risk" in reason for reason in net_gate.rejection_reasons):
            simple_reasons.append("net_reward_risk_too_low")
        if any(
            marker in reason
            for reason in net_gate.rejection_reasons
            for marker in (
                "expected net edge",
                "cost drag",
                "covers",
                "minimum profitable move",
            )
        ):
            simple_reasons.append("costs_consume_target")
        if final_score < threshold:
            simple_reasons.append("final_score_below_threshold")
        if observer_mode:
            simple_reasons.append("mode_restriction")
        if not symbol_tradable:
            simple_reasons.append("poor_data_quality")
        if symbol_has_open_trade:
            simple_reasons.append("symbol_open_trade_exists")
            simple_reasons.append("mode_restriction")
        if bool(cooldown_state.get("active")):
            simple_reasons.append("cooldown_active")
            simple_reasons.append("mode_restriction")
        if symbol_session_entry_count >= 2:
            simple_reasons.append("symbol_session_entry_cap")
            simple_reasons.append("mode_restriction")
        if risk_manager.recommended_action == "BLOCK" and "risk_too_high_capital_protection" not in simple_reasons:
            simple_reasons.append("risk_blocked")
        return list(dict.fromkeys(simple_reasons)) or ["general_rejection"]

    @staticmethod
    def _build_near_approval_snapshot(
        *,
        approved: bool,
        paper_mode: str,
        final_score: float,
        threshold: float,
        net_gate,
        active_cost_snapshot,
        signal_actionability: str,
        tf_alignment: TimeframeAlignment,
        score_breakdown: dict[str, float],
        risk_manager,
        symbol_has_open_trade: bool,
        cooldown_state: dict[str, object],
        symbol_session_entry_count: int,
        symbol_tradable: bool,
        stale_blocked: bool,
        observer_mode: bool,
    ) -> dict[str, object]:
        with_laxer_threshold = final_score >= (threshold * 0.95)
        without_secondary_contradiction = (
            any(timeframe in {"30m", "1h"} for timeframe in tf_alignment.rejecting_timeframes)
            and (final_score + score_breakdown.get("contradiction_penalty", 0.0)) >= threshold
        )
        with_smaller_size = (
            paper_mode == "PAPER_EXPLORATION"
            and not symbol_has_open_trade
            and not bool(cooldown_state.get("active"))
            and symbol_tradable
            and not stale_blocked
            and not observer_mode
            and signal_actionability != "NO_SIGNAL"
            and net_gate.approved
            and risk_manager.risk_mode == "CAPITAL_PROTECTION"
            and risk_manager.position_size_pct > 0
        )
        with_more_room_for_entries = (
            paper_mode == "PAPER_EXPLORATION"
            and symbol_session_entry_count >= 2
            and signal_actionability != "NO_SIGNAL"
            and net_gate.approved
            and not symbol_has_open_trade
            and not bool(cooldown_state.get("active"))
            and symbol_tradable
            and not stale_blocked
            and not observer_mode
        )
        near_approved = (
            not approved
            and paper_mode == "PAPER_EXPLORATION"
            and signal_actionability != "NO_SIGNAL"
            and net_gate.approved
            and symbol_tradable
            and not stale_blocked
            and not observer_mode
            and (
                with_laxer_threshold
                or with_smaller_size
                or without_secondary_contradiction
                or with_more_room_for_entries
            )
        )
        return {
            "near_approved_exploration": near_approved,
            "expected_net_edge_pct": round(float(net_gate.expected_net_edge_pct), 6),
            "required_break_even_move_pct": round(float(active_cost_snapshot.minimum_profitable_move_pct), 6),
            "expected_move_pct": round(float(net_gate.expected_move_pct), 6),
            "would_open_with_5pct_laxer_threshold": with_laxer_threshold,
            "would_open_with_smaller_size": with_smaller_size,
            "would_open_without_secondary_contradiction": without_secondary_contradiction,
            "would_open_with_more_symbol_entry_room": with_more_room_for_entries,
        }

    def _select_paper_mode(
        self,
        *,
        observer_mode: bool,
        assessment_is_stale: bool,
        provider_used: str,
        symbol_tradable: bool,
        risk_manager_action: str,
        market_risk_mode: str,
        contradiction_score: float,
        alignment_label: str,
        meta_sample_strength: str,
        open_positions: int,
        recent_exploration_trades: int,
        recent_rejected_opportunities: int,
        has_positive_exploration_edge: bool,
        has_positive_selective_edge: bool,
        symbol_has_open_trade: bool,
        symbol_in_cooldown: bool,
        signal_actionability: str,
        symbol_session_entry_count: int,
    ) -> str:
        if observer_mode:
            return "OBSERVE_ONLY"
        if assessment_is_stale or risk_manager_action == "BLOCK" or not symbol_tradable:
            return "OBSERVE_ONLY"
        if market_risk_mode == "DO_NOT_TRADE":
            return "OBSERVE_ONLY"
        if signal_actionability == "NO_SIGNAL":
            return "OBSERVE_ONLY"
        if symbol_has_open_trade or symbol_in_cooldown:
            return "OBSERVE_ONLY"
        if symbol_session_entry_count >= self._settings.exploration_max_entries_per_symbol_session:
            return "OBSERVE_ONLY"
        if contradiction_score >= 0.9 or alignment_label == "CONTRADICTED":
            return "OBSERVE_ONLY"
        if open_positions >= self._settings.exploration_max_open_positions:
            return "OBSERVE_ONLY"
        if not has_positive_exploration_edge:
            return "OBSERVE_ONLY"
        if not self._settings.paper_mode_auto:
            return "PAPER_SELECTIVE" if has_positive_selective_edge else "PAPER_EXPLORATION"
        if market_risk_mode == "CAPITAL_PROTECTION":
            return "PAPER_EXPLORATION"
        if (
            has_positive_selective_edge
            and meta_sample_strength in {"USABLE", "STRONG", "VERY_STRONG"}
            and contradiction_score <= 0.28
            and alignment_label in {"FULL_ALIGNMENT", "SCALP_ONLY"}
        ):
            return "PAPER_SELECTIVE"
        if has_positive_exploration_edge and recent_exploration_trades < self._settings.exploration_max_trades_per_hour:
            return "PAPER_EXPLORATION"
        if recent_rejected_opportunities >= 3 and has_positive_exploration_edge:
            return "PAPER_EXPLORATION"
        return "PAPER_EXPLORATION"

    @staticmethod
    def _paper_mode_reason(
        *,
        paper_mode: str,
        observer_mode: bool,
        assessment_is_stale: bool,
        provider_used: str,
        symbol_tradable: bool,
        contradiction_score: float,
        risk_manager_action: str,
        market_risk_mode: str,
        exploration_gate,
        selective_gate,
        symbol_has_open_trade: bool,
        symbol_in_cooldown: bool,
        symbol_session_entry_count: int,
    ) -> str:
        if observer_mode:
            return "technical_block: observer mode requested"
        if assessment_is_stale:
            return "data_not_fresh: stale market data detected"
        if symbol_has_open_trade:
            return "mode_restriction: symbol already has an open paper trade"
        if symbol_in_cooldown:
            return "mode_restriction: symbol is cooling down after a recent loss"
        if symbol_session_entry_count >= 2:
            return "mode_restriction: symbol reached the exploration session entry cap"
        if risk_manager_action == "BLOCK":
            return "risk_too_high: risk manager blocked new entries"
        if market_risk_mode == "DO_NOT_TRADE":
            return "risk_too_high: market state recommends capital protection"
        if market_risk_mode == "CAPITAL_PROTECTION" and paper_mode == "PAPER_EXPLORATION":
            return "risk_reduced_exploration: capital protection reduced the size, but bounded exploration remains allowed"
        if not symbol_tradable:
            return "technical_block: symbol not tradable today"
        if contradiction_score >= 0.9:
            return "contradiction_too_high: multi-timeframe conflict is critical"
        if paper_mode == "PAPER_SELECTIVE":
            if provider_used == "LOCAL_SQLITE":
                return "paper_selective_with_fallback: setup is strong enough despite fallback data, but confidence is penalized"
            return "paper_selective: historical and current conditions justify stricter execution"
        if paper_mode == "PAPER_EXPLORATION":
            if exploration_gate.approved and not selective_gate.approved:
                if provider_used == "LOCAL_SQLITE":
                    return "paper_exploration_with_fallback: bounded exploration is allowed on fallback data with reduced confidence"
                return "operating_mode_too_restrictive: selective mode would reject, exploration allows bounded learning"
            if provider_used == "LOCAL_SQLITE":
                return "paper_exploration_with_fallback: fallback provider is acceptable for paper exploration when the setup remains net-positive"
            return "paper_exploration: setup has positive edge but still lacks stronger historical proof"
        if not exploration_gate.approved:
            return "no_positive_edge: exploration gate did not find a net-positive setup"
        return "costs_too_high: setup quality is still insufficient after estimated costs"

    def _build_final_score_breakdown(
        self,
        *,
        strategy_score: float,
        market_alignment_score: float,
        multi_timeframe_alignment_score: float,
        economics_score: float,
        data_quality_score: float,
        contradiction_score: float,
        cost_drag_pct: float,
        critic_score: float,
        drawdown_pct: float,
        open_positions: int,
        provider_used: str,
        paper_mode: str,
    ) -> dict[str, float]:
        exploration_mode = paper_mode == "PAPER_EXPLORATION"
        positive_strategy = round(strategy_score * (0.34 if exploration_mode else 0.3), 6)
        positive_market = round(market_alignment_score * (0.24 if exploration_mode else 0.2), 6)
        positive_timeframe = round(multi_timeframe_alignment_score * (0.18 if exploration_mode else 0.2), 6)
        positive_economics = round(economics_score * (0.24 if exploration_mode else 0.3), 6)

        cost_penalty = round(min(0.12 if exploration_mode else 0.18, max(0.0, cost_drag_pct) * 0.18), 6)
        contradiction_penalty = round(min(0.1 if exploration_mode else 0.22, max(0.0, contradiction_score) * (0.14 if exploration_mode else 0.28)), 6)
        data_quality_penalty = round(min(0.1 if exploration_mode else 0.18, max(0.0, 1.0 - data_quality_score) * 0.14), 6)
        drawdown_penalty = round(
            min(0.05 if exploration_mode else 0.08, (abs(drawdown_pct) / max(self._settings.max_daily_drawdown_pct * 100, 0.000001)) * 0.05),
            6,
        )
        overtrading_penalty = round(
            min(0.03 if exploration_mode else 0.06, (open_positions / max(self._settings.exploration_max_open_positions, 1)) * 0.03),
            6,
        )
        critic_penalty = round(min(0.04 if exploration_mode else 0.08, max(0.0, 1.0 - critic_score) * 0.04), 6)
        provider_penalty = 0.02 if exploration_mode and provider_used == "LOCAL_SQLITE" else (0.04 if provider_used == "LOCAL_SQLITE" else 0.0)

        final_score = round(
            positive_strategy
            + positive_market
            + positive_timeframe
            + positive_economics
            - cost_penalty
            - contradiction_penalty
            - data_quality_penalty
            - drawdown_penalty
            - overtrading_penalty
            - critic_penalty
            - provider_penalty,
            6,
        )
        return {
            "strategy_score": round(strategy_score, 6),
            "market_alignment_score": round(market_alignment_score, 6),
            "multi_timeframe_alignment_score": round(multi_timeframe_alignment_score, 6),
            "economics_score": round(economics_score, 6),
            "positive_strategy": positive_strategy,
            "positive_market": positive_market,
            "positive_timeframe": positive_timeframe,
            "positive_economics": positive_economics,
            "cost_penalty": cost_penalty,
            "contradiction_penalty": contradiction_penalty,
            "data_quality_penalty": data_quality_penalty,
            "drawdown_penalty": drawdown_penalty,
            "overtrading_penalty": overtrading_penalty,
            "critic_penalty": critic_penalty,
            "provider_penalty": provider_penalty,
            "final_score": final_score,
        }

    def _resolve_final_score_threshold(
        self,
        *,
        paper_mode: str,
        timeframe: str,
        signal_actionability: str,
        operating_horizon_minutes: int | None,
    ) -> float:
        if paper_mode == "PAPER_EXPLORATION":
            threshold = self._settings.brain_min_final_score_exploration
            short_intraday_run = operating_horizon_minutes is not None and operating_horizon_minutes <= 60
            if short_intraday_run:
                if timeframe == "15m":
                    threshold -= 0.015
                elif timeframe == "30m":
                    threshold += 0.005
                elif timeframe in {"1h", "4h"}:
                    threshold += 0.015
            if signal_actionability == "WEAK_EXPLORABLE":
                threshold -= 0.01
            elif signal_actionability == "VALID_NON_SELECTIVE":
                threshold -= 0.005
            return round(max(0.28, threshold), 6)
        if paper_mode == "PAPER_SELECTIVE":
            return float(self._settings.brain_min_final_score_selective)
        return float(self._settings.brain_min_final_score)

    @staticmethod
    def _classify_rejection(
        *,
        critic,
        net_gate,
        risk_manager,
        paper_mode: str,
        observer_mode: bool,
        symbol_tradable: bool,
        final_score: float,
        threshold: float,
        signal_actionability: str,
    ) -> tuple[str, str]:
        if observer_mode:
            return "OperatingMode", "PAPER_MODE"
        if signal_actionability == "NO_SIGNAL":
            return "TradingBrainOrchestrator", "SIGNAL"
        if risk_manager.recommended_action == "BLOCK":
            return "RiskManagerAgent", "RISK"
        if not symbol_tradable:
            return "SymbolSelectionAgent", "SYMBOL_FILTER"
        if critic.critic_decision == "REJECT":
            return "StrategyCriticAgent", "CRITIC"
        if not net_gate.approved:
            return "NetProfitabilityGate", "NET_GATE"
        if final_score < threshold:
            return "TradingBrainOrchestrator", "FINAL_SCORE"
        if paper_mode == "OBSERVE_ONLY":
            return "OperatingMode", "PAPER_MODE"
        return "TradingBrainOrchestrator", "GENERAL"

    def _evaluate_pending_no_trade_outcomes(self) -> None:
        horizon = max(3, self._settings.simulated_max_hold_candles)
        for row in self._database.get_unevaluated_no_trade_brain_decisions(limit=25):
            payload = json.loads(str(row.get("raw_payload") or "{}"))
            proposal = payload.get("best_proposal", {}) if isinstance(payload, dict) else {}
            direction = str(proposal.get("proposed_decision", "NO_TRADE"))
            if direction not in {"LONG", "SHORT"}:
                self._database.update_brain_decision_outcome(decision_id=int(row["id"]), outcome_label="INSUFFICIENT_DATA")
                continue
            future_candles = self._database.get_next_candles(
                symbol=str(row["symbol"]),
                timeframe=str(row["timeframe"]),
                after_close_time=str(row["timestamp"]),
                limit=horizon,
            )
            if len(future_candles) < horizon:
                continue
            entry_price = future_candles[0].open
            required_move = float(row.get("total_cost_pct") or 0.0)
            if entry_price <= 0:
                self._database.update_brain_decision_outcome(decision_id=int(row["id"]), outcome_label="INSUFFICIENT_DATA")
                continue
            if direction == "LONG":
                max_favorable = max((((candle.high - entry_price) / entry_price) * 100) for candle in future_candles)
                close_return = ((future_candles[-1].close - entry_price) / entry_price) * 100
                max_adverse = min((((candle.low - entry_price) / entry_price) * 100) for candle in future_candles)
            else:
                max_favorable = max((((entry_price - candle.low) / entry_price) * 100) for candle in future_candles)
                close_return = ((entry_price - future_candles[-1].close) / entry_price) * 100
                max_adverse = min((((entry_price - candle.high) / entry_price) * 100) for candle in future_candles)
            would_trade_if_exploration_enabled = bool(row.get("would_trade_if_exploration_enabled"))
            if max_favorable >= max(required_move, 0.05) and close_return > 0:
                outcome = "MISSED_OPPORTUNITY" if would_trade_if_exploration_enabled else "OVERFILTERED"
            elif max_adverse <= -max(required_move, 0.05):
                outcome = "BAD_TRADE_AVOIDED"
            else:
                outcome = "GOOD_AVOIDANCE"
            self._database.update_brain_decision_outcome(decision_id=int(row["id"]), outcome_label=outcome)

    @staticmethod
    def _reject(symbol: str, timeframe: str, decision: str, market_state: str, risk_mode: str, provider_used: str, data_stale: bool, reason: str, payload: dict[str, object]) -> BrainDecision:
        return BrainDecision(
            symbol=symbol,
            timeframe=timeframe,
            final_decision=decision,
            selected_strategy="NO_TRADE",
            market_state=market_state,
            risk_mode=risk_mode,
            confidence=0.0,
            final_score=0.0,
            expected_move_pct=0.0,
            total_cost_pct=0.0,
            expected_net_edge_pct=0.0,
            risk_reward_ratio=0.0,
            cost_coverage_multiple=0.0,
            approved=False,
            rejection_reason=reason,
            entry_reason=reason,
            exit_reason=reason,
            provider_used=provider_used,
            data_stale=data_stale,
            paper_mode="OBSERVE_ONLY",
            raw_payload=payload,
        )
