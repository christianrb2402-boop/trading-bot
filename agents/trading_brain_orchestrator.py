from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Any

from agents.breakout_agent import BreakoutAgent
from agents.cost_model_agent import CostModelAgent
from agents.decision_orchestrator import DecisionOrchestrator
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
    RiskEventRecord,
    StrategyVoteRecord,
)
from core.ledger_reconciler import LedgerReconciler
from data.market_data_provider import ProviderRouter
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

        timeframe_contexts = self._build_timeframe_contexts(symbol=symbol, execution_timeframe=timeframe, current_context=market_context)
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

        cost_snapshot = self._cost_model_agent.estimate(
            entry_price=recent_candles[-1].close,
            direction=best_proposal.proposed_decision if best_proposal.proposed_decision in {"LONG", "SHORT"} else "LONG",
            position_size_usd=min(self._settings.simulated_position_size_usd, total_equity * risk_manager.position_size_pct),
            volatility_pct=float(feature_snapshot.payload.get("atr_pct", 0.0)),
            market_type=self._settings.simulated_market_type,
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
        risk_reward = self._risk_reward_agent.evaluate(signal=delta_signal, cost_snapshot=cost_snapshot)
        net_gate = self._net_profitability_gate.evaluate(signal=delta_signal, cost_snapshot=cost_snapshot)
        meta_learning = self._meta_learning_agent.assess(
            symbol=symbol,
            timeframe=timeframe,
            strategy_name=best_proposal.strategy_name,
            market_state=market_state.market_state,
        )
        tf_alignment = self._decision_orchestrator.assess_timeframes(
            symbol=symbol,
            direction=best_proposal.proposed_decision if best_proposal.proposed_decision in {"LONG", "SHORT"} else direction_bias,
            execution_timeframe=timeframe,
            timeframe_contexts=timeframe_contexts,
        )
        duplicate_setup = False
        if best_proposal.proposed_decision in {"LONG", "SHORT"}:
            duplicate_setup = self._is_duplicate_setup(symbol=symbol, timeframe=timeframe, direction=best_proposal.proposed_decision, setup_signature=best_proposal.strategy_name)
        critic = self._strategy_critic_agent.critique(
            proposal=best_proposal.as_dict(),
            total_cost_pct=float(cost_snapshot.minimum_profitable_move_pct),
            expected_net_edge_pct=float(net_gate.expected_net_edge_pct),
            expected_net_reward_risk=float(net_gate.expected_net_reward_risk),
            timeframe_alignment=tf_alignment.timeframe_alignment,
            contradiction_score=tf_alignment.contradiction_score,
            market_state=market_state.market_state,
            is_stale=assessment.is_stale and not allow_stale_fallback,
            gap_count=assessment.gap_count,
            duplicate_setup=duplicate_setup,
            loss_streak=risk_manager.loss_streak,
            data_quality_score=symbol_selection.data_quality_score,
        )

        strategy_score = best_proposal.confidence
        market_alignment_score = market_state.confidence
        multi_timeframe_alignment_score = tf_alignment.alignment_score
        risk_reward_score = min(1.0, float(risk_reward.expected_net_reward_risk) / 2.0)
        expected_net_edge_score = min(1.0, max(float(net_gate.expected_net_edge_pct), 0.0) / max(self._settings.min_expected_net_edge_pct, 0.000001))
        historical_learning_score = max(0.0, 0.5 + meta_learning.confidence_adjustment)
        cost_penalty = min(1.0, float(cost_snapshot.cost_drag_pct))
        drawdown_penalty = min(1.0, abs(drawdown_pct) / max(self._settings.max_daily_drawdown_pct * 100, 0.000001))
        data_quality_penalty = max(0.0, 1.0 - symbol_selection.data_quality_score)
        contradiction_penalty = tf_alignment.contradiction_score
        overtrading_penalty = min(1.0, len(self._database.get_open_paper_positions()) / max(self._settings.max_open_positions, 1))
        critic_penalty = max(0.0, 1.0 - critic.critic_score)

        final_score = (
            strategy_score
            + market_alignment_score
            + multi_timeframe_alignment_score
            + risk_reward_score
            + expected_net_edge_score
            + historical_learning_score
            - cost_penalty
            - drawdown_penalty
            - data_quality_penalty
            - contradiction_penalty
            - overtrading_penalty
            - critic_penalty
        )

        approved = (
            best_proposal.proposed_decision in {"LONG", "SHORT"}
            and selection.primary_strategy != "NO_TRADE"
            and market_state.recommended_risk_mode != "DO_NOT_TRADE"
            and risk_manager.recommended_action != "BLOCK"
            and symbol_selection.tradable_today
            and net_gate.approved
            and critic.critic_decision != "REJECT"
            and final_score >= self._settings.brain_min_final_score
            and not (assessment.is_stale and not allow_stale_fallback)
            and not observer_mode
        )
        rejection_reason = ""
        if not approved:
            reasons = [
                critic.rejection_reason or "",
                net_gate.reason if not net_gate.approved else "",
                risk_manager.reason if risk_manager.recommended_action == "BLOCK" else "",
                "observer mode only" if observer_mode else "",
                "symbol not tradable today" if not symbol_selection.tradable_today else "",
                f"final score {round(final_score, 4)} below minimum {self._settings.brain_min_final_score}" if final_score < self._settings.brain_min_final_score else "",
            ]
            rejection_reason = "; ".join(reason for reason in reasons if reason)
        final_decision = best_proposal.proposed_decision if approved else "NO_TRADE"
        exit_reason = net_gate.close_condition if approved else rejection_reason or "no trade"

        payload = {
            "provider_used": provider_result.provider_used,
            "market_data": assessment.as_dict(),
            "features": feature_snapshot.as_dict(),
            "market_context": market_context,
            "market_state": market_state.as_dict(),
            "strategy_selection": selection.as_dict(),
            "best_proposal": best_proposal.as_dict(),
            "cost_snapshot": cost_snapshot.as_dict(),
            "risk_reward": risk_reward.as_dict(),
            "net_gate": net_gate.as_dict(),
            "critic": critic.as_dict(),
            "risk_manager": risk_manager.as_dict(),
            "meta_learning": meta_learning.as_dict(),
            "timeframe_alignment": tf_alignment.as_dict(),
            "score_breakdown": {
                "strategy_score": strategy_score,
                "market_alignment_score": market_alignment_score,
                "multi_timeframe_alignment_score": multi_timeframe_alignment_score,
                "risk_reward_score": risk_reward_score,
                "expected_net_edge_score": expected_net_edge_score,
                "historical_learning_score": historical_learning_score,
                "cost_penalty": cost_penalty,
                "drawdown_penalty": drawdown_penalty,
                "data_quality_penalty": data_quality_penalty,
                "contradiction_penalty": contradiction_penalty,
                "overtrading_penalty": overtrading_penalty,
                "critic_penalty": critic_penalty,
            },
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
                    cost_estimate_pct=cost_snapshot.minimum_profitable_move_pct,
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
                raw_payload=json.dumps(payload, ensure_ascii=True),
            )
        )
        self._database.insert_agent_decision(
            AgentDecisionRecord(
                timestamp=timestamp,
                agent_name="TradingBrainOrchestrator",
                symbol=symbol,
                timeframe=timeframe,
                decision=final_decision,
                confidence=round(max(0.0, min(1.0, best_proposal.confidence + meta_learning.confidence_adjustment - critic_penalty * 0.1)), 6),
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

        return BrainDecision(
            symbol=symbol,
            timeframe=timeframe,
            final_decision=final_decision,
            selected_strategy=best_proposal.strategy_name,
            market_state=market_state.market_state,
            risk_mode=risk_manager.risk_mode,
            confidence=round(max(0.0, min(1.0, best_proposal.confidence + meta_learning.confidence_adjustment - critic_penalty * 0.1)), 6),
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
            raw_payload=payload,
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
        for strategy_name in names:
            if strategy_name in {"NO_TRADE", ""}:
                continue
            agent = self._strategy_agents.get(strategy_name)
            if agent is None:
                continue
            proposals.append(agent.evaluate(symbol=symbol, timeframe=timeframe, features=features, market_state=market_state, direction_bias=direction_bias))
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

    def _build_timeframe_contexts(self, *, symbol: str, execution_timeframe: str, current_context: dict[str, object]) -> dict[str, dict[str, object]]:
        contexts: dict[str, dict[str, object]] = {execution_timeframe: current_context}
        for timeframe in (*self._settings.context_timeframes, *self._settings.structural_timeframes):
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
            raw_payload=payload,
        )
