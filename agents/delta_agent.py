from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence

from agents.market_context_agent import MarketContextAgent
from config.settings import Settings
from core.database import Database, StoredCandle


@dataclass(slots=True, frozen=True)
class DeltaSignal:
    symbol: str
    timeframe: str
    signal: bool
    signal_type: str
    direction: str
    decision_type: str
    signal_tier: str
    k_value: float
    signal_strength: float
    roc_price: float
    roc_volume: float
    confidence: float
    price: float
    volume: float
    trend_direction: str
    volatility_regime: str
    momentum_strength: float
    momentum_confirmed: bool
    volatility_pct: float
    volume_spike: bool
    volume_regime: str
    market_regime: str
    volatility_bucket: str
    momentum_bucket: str
    setup_signature: str
    feedback_adjustment: float
    thresholds_failed: tuple[str, ...]
    conditions_met: tuple[str, ...]
    risks_detected: tuple[str, ...]
    reason: str
    explanation: str
    timestamp: str

    def as_dict(self) -> dict[str, str | float | bool | tuple[str, ...]]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "signal": self.signal,
            "signal_type": self.signal_type,
            "direction": self.direction,
            "decision_type": self.decision_type,
            "signal_tier": self.signal_tier,
            "k": self.k_value,
            "k_value": self.k_value,
            "signal_strength": self.signal_strength,
            "roc_price": self.roc_price,
            "roc_volume": self.roc_volume,
            "confidence": self.confidence,
            "price": self.price,
            "volume": self.volume,
            "trend_direction": self.trend_direction,
            "volatility_regime": self.volatility_regime,
            "momentum_strength": self.momentum_strength,
            "momentum_confirmed": self.momentum_confirmed,
            "volatility_pct": self.volatility_pct,
            "volume_spike": self.volume_spike,
            "volume_regime": self.volume_regime,
            "market_regime": self.market_regime,
            "volatility_bucket": self.volatility_bucket,
            "momentum_bucket": self.momentum_bucket,
            "setup_signature": self.setup_signature,
            "feedback_adjustment": self.feedback_adjustment,
            "thresholds_failed": self.thresholds_failed,
            "conditions_met": self.conditions_met,
            "risks_detected": self.risks_detected,
            "reason": self.reason,
            "explanation": self.explanation,
            "timestamp": self.timestamp,
        }


@dataclass(slots=True, frozen=True)
class HistoricalDeltaSignal:
    symbol: str
    timeframe: str
    open_time: str
    entry_price: float
    roc_price: float
    roc_volume: float
    k: float
    signal: bool
    signal_type: str
    confidence: float
    direction: str
    reason: str

    def as_dict(self) -> dict[str, str | float | bool]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "open_time": self.open_time,
            "entry_price": self.entry_price,
            "roc_price": self.roc_price,
            "roc_volume": self.roc_volume,
            "k": self.k,
            "signal": self.signal,
            "signal_type": self.signal_type,
            "confidence": self.confidence,
            "direction": self.direction,
            "reason": self.reason,
        }


@dataclass(slots=True, frozen=True)
class DeltaWindowSummary:
    requested_window: int
    candles_used: int
    complete_window: bool
    total_points: int
    signal_count: int
    signal_percentage: float
    last_k: float

    def as_dict(self) -> dict[str, int | float | bool]:
        return {
            "requested_window": self.requested_window,
            "candles_used": self.candles_used,
            "complete_window": self.complete_window,
            "total_points": self.total_points,
            "signal_count": self.signal_count,
            "signal_percentage": self.signal_percentage,
            "last_k": self.last_k,
        }


class DeltaAgent:
    def __init__(self, database: Database, threshold: float = 0.5, settings: Settings | None = None) -> None:
        self._database = database
        self._threshold = threshold
        self._weak_threshold_factor = settings.delta_weak_threshold_factor if settings else 0.1
        self._strong_threshold_factor = settings.delta_strong_threshold_factor if settings else 2.0
        self._market_context_agent = MarketContextAgent(database=database)

    def evaluate(
        self,
        symbol: str,
        timeframe: str,
        market_context: dict[str, str | float | bool | int] | None = None,
    ) -> dict[str, str | float | bool | tuple[str, ...]]:
        context = market_context or self._market_context_agent.evaluate(symbol=symbol, timeframe=timeframe)
        candles = self._database.get_recent_candles(symbol=symbol, timeframe=timeframe, limit=2)
        return self.evaluate_from_candles(symbol=symbol, timeframe=timeframe, candles=candles, market_context=context)

    def evaluate_from_candles(
        self,
        *,
        symbol: str,
        timeframe: str,
        candles: Sequence[StoredCandle],
        market_context: dict[str, str | float | bool | int] | None = None,
        relaxation_factor: float = 1.0,
    ) -> dict[str, str | float | bool | tuple[str, ...]]:
        context = market_context or self._market_context_agent.evaluate(symbol=symbol, timeframe=timeframe, candles=candles)
        if len(candles) < 2:
            return DeltaSignal(
                symbol=symbol,
                timeframe=timeframe,
                signal=False,
                signal_type="NONE",
                direction="NONE",
                decision_type="NONE",
                signal_tier="REJECTED",
                k_value=0.0,
                signal_strength=0.0,
                roc_price=0.0,
                roc_volume=0.0,
                confidence=0.0,
                price=0.0,
                volume=0.0,
                trend_direction=str(context.get("trend_direction", "SIDEWAYS")),
                volatility_regime=str(context.get("volatility_regime", "LOW")),
                momentum_strength=float(context.get("momentum_strength", 0.0)),
                momentum_confirmed=bool(context.get("momentum_confirmed", False)),
                volatility_pct=float(context.get("volatility_pct", 0.0)),
                volume_spike=bool(context.get("volume_spike", False)),
                volume_regime=str(context.get("volume_regime", "NORMAL")),
                market_regime=str(context.get("market_regime", "RANGING")),
                volatility_bucket="UNKNOWN",
                momentum_bucket="UNKNOWN",
                setup_signature="NO_DATA",
                feedback_adjustment=0.0,
                thresholds_failed=("weak_threshold",),
                conditions_met=(),
                risks_detected=("not enough closed candles",),
                reason="NO_DATA because not enough closed candles",
                explanation="No signal was generated because the Delta agent does not yet have two closed candles to compare.",
                timestamp=datetime.now(timezone.utc).isoformat(),
            ).as_dict()

        previous_candle, current_candle = candles[-2], candles[-1]
        roc_price, roc_volume, k, direction = self._calculate_signal_metrics(previous_candle, current_candle)
        decision = self._build_decision(
            symbol=symbol,
            timeframe=timeframe,
            current_candle=current_candle,
            roc_price=roc_price,
            roc_volume=roc_volume,
            k=k,
            context=context,
            relaxation_factor=relaxation_factor,
        )
        return decision.as_dict()

    def evaluate_windows(
        self,
        symbol: str,
        timeframe: str,
        windows: Sequence[int] = (10, 20, 50),
    ) -> dict[str, str | float | int | list[dict[str, int | float | bool]]]:
        summaries: list[DeltaWindowSummary] = []

        for window in windows:
            candles = self._database.get_recent_candles(symbol=symbol, timeframe=timeframe, limit=window)
            summaries.append(self._evaluate_window(candles=candles, requested_window=window))

        total_points = sum(summary.total_points for summary in summaries)
        total_signals = sum(summary.signal_count for summary in summaries)
        signal_percentage = round((total_signals / total_points) * 100, 2) if total_points else 0.0

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "threshold": self._threshold,
            "total_signals": total_signals,
            "total_points": total_points,
            "signal_percentage": signal_percentage,
            "windows": [summary.as_dict() for summary in summaries],
        }

    def get_historical_signals(self, symbol: str, timeframe: str) -> list[HistoricalDeltaSignal]:
        candles = self._database.get_candles(symbol=symbol, timeframe=timeframe)
        if len(candles) < 5:
            return []

        signals: list[HistoricalDeltaSignal] = []
        for index in range(1, len(candles)):
            previous_candle = candles[index - 1]
            current_candle = candles[index]
            recent_window = candles[max(0, index - 19) : index + 1]
            context = self._market_context_agent.evaluate(symbol=symbol, timeframe=timeframe, candles=recent_window)
            roc_price, roc_volume, k, _ = self._calculate_signal_metrics(previous_candle, current_candle)
            decision = self._build_decision(
                symbol=symbol,
                timeframe=timeframe,
                current_candle=current_candle,
                roc_price=roc_price,
                roc_volume=roc_volume,
                k=k,
                context=context,
                relaxation_factor=1.0,
            )
            decision_payload = decision.as_dict()
            signals.append(
                HistoricalDeltaSignal(
                    symbol=symbol,
                    timeframe=timeframe,
                    open_time=current_candle.open_time,
                    entry_price=current_candle.close,
                    roc_price=float(decision_payload["roc_price"]),
                    roc_volume=float(decision_payload["roc_volume"]),
                    k=float(decision_payload["k_value"]),
                    signal=bool(decision_payload["signal"]),
                    signal_type=str(decision_payload["signal_type"]),
                    confidence=float(decision_payload["confidence"]),
                    direction=str(decision_payload["direction"]),
                    reason=str(decision_payload["reason"]),
                )
            )
        return signals

    @staticmethod
    def _calculate_roc(previous_value: float, current_value: float) -> float:
        if previous_value == 0:
            return 0.0
        return ((current_value - previous_value) / previous_value) * 100

    def _evaluate_window(
        self,
        candles: Sequence[StoredCandle],
        requested_window: int,
    ) -> DeltaWindowSummary:
        if len(candles) < 5:
            return DeltaWindowSummary(
                requested_window=requested_window,
                candles_used=len(candles),
                complete_window=len(candles) >= requested_window,
                total_points=0,
                signal_count=0,
                signal_percentage=0.0,
                last_k=0.0,
            )

        signals = []
        k_values = []
        for index in range(1, len(candles)):
            previous_candle = candles[index - 1]
            current_candle = candles[index]
            recent_window = candles[max(0, index - 19) : index + 1]
            context = self._market_context_agent.evaluate(symbol=current_candle.symbol, timeframe=current_candle.timeframe, candles=recent_window)
            roc_price, roc_volume, k, _ = self._calculate_signal_metrics(previous_candle, current_candle)
            decision = self._build_decision(
                symbol=current_candle.symbol,
                timeframe=current_candle.timeframe,
                current_candle=current_candle,
                roc_price=roc_price,
                roc_volume=roc_volume,
                k=k,
                context=context,
                relaxation_factor=1.0,
            ).as_dict()
            signals.append(bool(decision["signal"]))
            k_values.append(float(decision["k_value"]))

        total_points = len(k_values)
        signal_count = sum(1 for item in signals if item)
        signal_percentage = round((signal_count / total_points) * 100, 2) if total_points else 0.0

        return DeltaWindowSummary(
            requested_window=requested_window,
            candles_used=len(candles),
            complete_window=len(candles) >= requested_window,
            total_points=total_points,
            signal_count=signal_count,
            signal_percentage=signal_percentage,
            last_k=round(k_values[-1], 6) if k_values else 0.0,
        )

    def _calculate_signal_metrics(
        self,
        previous_candle: StoredCandle,
        current_candle: StoredCandle,
    ) -> tuple[float, float, float, str]:
        roc_price = self._calculate_roc(previous_candle.close, current_candle.close)
        roc_volume = self._calculate_roc(previous_candle.volume, current_candle.volume)
        direction = self._resolve_direction(roc_price)
        k = abs(roc_price) * max(roc_volume, 0.0)
        return roc_price, roc_volume, k, direction

    def _build_decision(
        self,
        *,
        symbol: str,
        timeframe: str,
        current_candle: StoredCandle,
        roc_price: float,
        roc_volume: float,
        k: float,
        context: dict[str, str | float | bool | int],
        relaxation_factor: float,
    ) -> DeltaSignal:
        trend_direction = str(context.get("trend_direction", "SIDEWAYS"))
        momentum_strength = float(context.get("momentum_strength", 0.0))
        momentum_confirmed = bool(context.get("momentum_confirmed", False))
        volatility_pct = float(context.get("volatility_pct", 0.0))
        volatility_regime = str(context.get("volatility_regime", self._volatility_bucket(volatility_pct)))
        volume_spike = bool(context.get("volume_spike", False))
        volume_regime = str(context.get("volume_regime", "NORMAL"))
        market_regime = str(context.get("market_regime", "RANGING"))
        volatility_bucket = self._volatility_bucket(volatility_pct)
        momentum_bucket = self._momentum_bucket(momentum_strength)
        effective_relaxation = max(0.05, relaxation_factor)
        weak_threshold = max(self._threshold * self._weak_threshold_factor * effective_relaxation, 0.000001)
        medium_threshold = max(self._threshold * effective_relaxation, weak_threshold)
        strong_threshold = max(self._threshold * self._strong_threshold_factor * effective_relaxation, medium_threshold)

        base_direction = self._resolve_direction(roc_price)
        threshold_ok = k > medium_threshold
        volatility_ok = volatility_pct >= 0.05
        trend_aligned = (
            (base_direction == "LONG" and trend_direction == "UP")
            or (base_direction == "SHORT" and trend_direction == "DOWN")
        )
        regime_ok = market_regime == "TRENDING"

        conditions_met: list[str] = []
        risks_detected: list[str] = []
        thresholds_failed: list[str] = []

        if k >= strong_threshold:
            signal_tier = "STRONG"
            conditions_met.append(f"k_value {round(k, 6)} exceeded strong threshold {round(strong_threshold, 6)}")
        elif k >= medium_threshold:
            signal_tier = "MEDIUM"
            conditions_met.append(f"k_value {round(k, 6)} exceeded medium threshold {round(medium_threshold, 6)}")
            thresholds_failed.append("strong_threshold")
        elif k >= weak_threshold:
            signal_tier = "WEAK"
            conditions_met.append(f"k_value {round(k, 6)} exceeded weak threshold {round(weak_threshold, 6)}")
            thresholds_failed.extend(("strong_threshold", "medium_threshold"))
        else:
            signal_tier = "REJECTED"
            thresholds_failed.extend(("strong_threshold", "medium_threshold", "weak_threshold"))
            risks_detected.append(
                f"k_value stayed below weak threshold {round(weak_threshold, 6)}"
            )

        if roc_price > 0:
            conditions_met.append(f"ROC_price was positive at {round(roc_price, 6)}%")
        elif roc_price < 0:
            conditions_met.append(f"ROC_price was negative at {round(roc_price, 6)}%")
        else:
            risks_detected.append("ROC_price was neutral")

        if trend_aligned:
            conditions_met.append(f"trend alignment confirmed with market trend {trend_direction}")
        else:
            risks_detected.append(f"trend alignment failed because market trend is {trend_direction}")

        if momentum_confirmed:
            conditions_met.append(f"momentum confirmed at strength {round(momentum_strength, 6)}")
        else:
            risks_detected.append("momentum confirmation was weak")

        if volatility_ok:
            conditions_met.append(f"volatility filter passed at {round(volatility_pct, 6)}%")
        else:
            risks_detected.append("volatility is too low for reliable execution")

        if volume_spike:
            conditions_met.append("volume spike supports conviction")
        else:
            risks_detected.append("no volume spike was present")

        if regime_ok:
            conditions_met.append("market regime is trending")
        else:
            risks_detected.append("market regime is ranging")

        setup_signature = self._build_setup_signature(
            direction=base_direction,
            trend_direction=trend_direction,
            market_regime=market_regime,
            volatility_bucket=volatility_bucket,
            momentum_bucket=momentum_bucket,
            volume_regime=volume_regime,
        )
        feedback_adjustment = 0.0
        similar_performance = self._database.get_similar_closed_trade_stats(
            setup_signature=setup_signature,
            direction=base_direction,
        )
        if int(similar_performance["total"]) >= 1:
            average_pnl_pct = float(similar_performance["average_pnl_pct"])
            winrate = float(similar_performance["winrate"])
            if average_pnl_pct < 0 or winrate < 45:
                feedback_adjustment = -0.15
                risks_detected.append(
                    f"historical feedback is weak for similar setup {setup_signature} "
                    f"with winrate {winrate}% and average pnl pct {average_pnl_pct}"
                )
            elif average_pnl_pct > 0 and winrate >= 55:
                feedback_adjustment = 0.1
                conditions_met.append(
                    f"historical feedback is favorable for similar setup {setup_signature} "
                    f"with winrate {winrate}% and average pnl pct {average_pnl_pct}"
                )

        raw_signal_type = "NONE"
        if signal_tier in {"STRONG", "MEDIUM", "WEAK"} and base_direction in {"LONG", "SHORT"}:
            raw_signal_type = base_direction

        actionable = raw_signal_type in {"LONG", "SHORT"}
        confidence = self._calculate_confidence(
            k=k,
            threshold_ok=signal_tier in {"STRONG", "MEDIUM", "WEAK"},
            trend_aligned=trend_aligned,
            momentum_confirmed=momentum_confirmed,
            volatility_ok=volatility_ok,
            volume_spike=volume_spike,
            regime_ok=regime_ok,
            weak_threshold=weak_threshold,
        )
        confidence = round(min(1.0, max(0.0, confidence + feedback_adjustment)), 6)

        reason = self._build_reason(
            raw_signal_type=raw_signal_type,
            signal_tier=signal_tier,
            conditions_met=conditions_met,
            risks_detected=risks_detected,
        )
        explanation = self._build_explanation(
            signal_type=raw_signal_type,
            signal_tier=signal_tier,
            conditions_met=conditions_met,
            risks_detected=risks_detected,
            thresholds_failed=thresholds_failed,
            feedback_adjustment=feedback_adjustment,
        )

        return DeltaSignal(
            symbol=symbol,
            timeframe=timeframe,
            signal=actionable,
            signal_type=raw_signal_type,
            direction=base_direction,
            decision_type=raw_signal_type,
            signal_tier=signal_tier,
            k_value=round(k, 6),
            signal_strength=round(k, 6),
            roc_price=round(roc_price, 6),
            roc_volume=round(roc_volume, 6),
            confidence=confidence,
            price=round(current_candle.close, 6),
            volume=round(current_candle.volume, 6),
            trend_direction=trend_direction,
            volatility_regime=volatility_regime,
            momentum_strength=round(momentum_strength, 6),
            momentum_confirmed=momentum_confirmed,
            volatility_pct=round(volatility_pct, 6),
            volume_spike=volume_spike,
            volume_regime=volume_regime,
            market_regime=market_regime,
            volatility_bucket=volatility_bucket,
            momentum_bucket=momentum_bucket,
            setup_signature=setup_signature,
            feedback_adjustment=round(feedback_adjustment, 6),
            thresholds_failed=tuple(thresholds_failed),
            conditions_met=tuple(conditions_met),
            risks_detected=tuple(risks_detected),
            reason=reason,
            explanation=explanation,
            timestamp=current_candle.close_time,
        )

    def _calculate_confidence(
        self,
        *,
        k: float,
        threshold_ok: bool,
        trend_aligned: bool,
        momentum_confirmed: bool,
        volatility_ok: bool,
        volume_spike: bool,
        regime_ok: bool,
        weak_threshold: float,
    ) -> float:
        base = min(1.0, max(0.0, k / max(weak_threshold * 4, 0.000001)))
        score = base * 0.45
        score += 0.15 if threshold_ok else 0.0
        score += 0.15 if trend_aligned else 0.0
        score += 0.1 if momentum_confirmed else 0.0
        score += 0.05 if volatility_ok else 0.0
        score += 0.05 if volume_spike else 0.0
        score += 0.05 if regime_ok else 0.0
        return round(min(1.0, max(0.0, score)), 6)

    @staticmethod
    def _build_reason(
        raw_signal_type: str,
        signal_tier: str,
        conditions_met: Sequence[str],
        risks_detected: Sequence[str],
    ) -> str:
        if raw_signal_type in {"LONG", "SHORT"}:
            return f"{raw_signal_type} {signal_tier} because " + ", ".join(conditions_met[:4])
        if risks_detected:
            return "NONE because " + ", ".join(risks_detected[:4])
        return "NONE because Delta conditions were not met"

    @staticmethod
    def _build_explanation(
        *,
        signal_type: str,
        signal_tier: str,
        conditions_met: Sequence[str],
        risks_detected: Sequence[str],
        thresholds_failed: Sequence[str],
        feedback_adjustment: float,
    ) -> str:
        signal_text = f"Signal: {signal_type}. Tier: {signal_tier}. "
        conditions_text = "Conditions met: " + ("; ".join(conditions_met) if conditions_met else "none") + ". "
        risks_text = "Risks detected: " + ("; ".join(risks_detected) if risks_detected else "none") + "."
        thresholds_text = " Thresholds failed: " + ("; ".join(thresholds_failed) if thresholds_failed else "none") + "."
        feedback_text = f" Learning feedback adjustment applied: {feedback_adjustment}."
        if signal_type == "NONE":
            return signal_text + "No actionable trade was produced. " + conditions_text + risks_text + thresholds_text + feedback_text
        return signal_text + "The setup passed the relaxed Delta filters. " + conditions_text + risks_text + thresholds_text + feedback_text

    @staticmethod
    def _volatility_bucket(volatility_pct: float) -> str:
        if volatility_pct >= 0.8:
            return "HIGH"
        if volatility_pct >= 0.25:
            return "NORMAL"
        return "LOW"

    @staticmethod
    def _momentum_bucket(momentum_strength: float) -> str:
        if momentum_strength >= 6:
            return "HIGH"
        if momentum_strength >= 2:
            return "MEDIUM"
        return "LOW"

    @staticmethod
    def _build_setup_signature(
        *,
        direction: str,
        trend_direction: str,
        market_regime: str,
        volatility_bucket: str,
        momentum_bucket: str,
        volume_regime: str,
    ) -> str:
        return "|".join((direction, trend_direction, market_regime, volatility_bucket, momentum_bucket, volume_regime))

    @staticmethod
    def _resolve_direction(roc_price: float) -> str:
        if roc_price > 0:
            return "LONG"
        if roc_price < 0:
            return "SHORT"
        return "NONE"
